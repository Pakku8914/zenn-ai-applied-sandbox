#!/usr/bin/env python3
"""セッション12：RAG 全体を評価するための道具一式。

ここに置くのは「判断に使う数字を作る関数」だけで、表示は各スクリプトに任せる。

提供するもの:
  - Bench            コーパス・チャンク・BM25 索引を1回だけ組み立てる入れ物
  - Bench.gold_hits  判定データから「本来渡すべきチャンク」を作る（上限測定の入力）
  - judge            1件の回答に対する自動検査（回答可能性・引用・根拠一致・忠実性）
  - classify_case    失敗を3層（コーパス / 検索 / 生成）に切り分ける
  - collect_cases    全クエリを回して Case の一覧にする

チャンク方式（fixed 400/80）・上位件数（5）・コンテキスト上限（2000字）は
合成カセットの前提と一致させてある。ここを変えるとカセットのキーが変わり、
FixtureClient が KeyError になる（＝カセット管理のコストを体験する仕掛け）。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.answer import Answer, answer_with_citations, verify_citations  # noqa: E402
from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.models import Chunk, Hit, Query  # noqa: E402
from ragkit.tokenize_ja import tokenize  # noqa: E402

TOP_K = 5          # 生成に渡す件数（カセットの前提）
MAX_CHARS = 2000   # コンテキストの上限文字数（カセットの前提）
MIN_FAITH = 0.35   # 忠実性の既定しきい値（章で振って決める値。固定の正解ではない）

LAYER_OK = "ok"
LAYER_CORPUS = "corpus"          # コーパスに情報が無い
LAYER_RETRIEVAL = "retrieval"    # 検索が取れていない
LAYER_GENERATION = "generation"  # 生成が使えていない
LAYERS = (LAYER_OK, LAYER_CORPUS, LAYER_RETRIEVAL, LAYER_GENERATION)


class Bench:
    """コーパス・チャンク・索引をまとめて1回だけ組み立てる。

    同じ索引を何度も作り直すと、遅いうえに「条件が揃っているか」が読めなくなる。
    評価の入口を1つにして、どのスクリプトも同じ土俵で測れるようにする。
    """

    def __init__(self, size: int = 400, overlap: int = 80) -> None:
        self.docs = load_docs()
        self.queries = load_queries()
        self.qrels = load_qrels()
        self.chunks = chunk_all(self.docs, "fixed", size=size, overlap=overlap)
        self.index = LexicalIndex().build(self.chunks)
        self.chunks_by_doc: dict[str, list[Chunk]] = {}
        for c in self.chunks:
            self.chunks_by_doc.setdefault(c.doc_id, []).append(c)
        self._tok_cache: dict[str, list[str]] = {}
        self._gold_cache: dict[tuple[str, int], list[Hit]] = {}

    # --- 基本操作 ---------------------------------------------------------
    def qrels_for(self, q: Query) -> dict[str, int]:
        return self.qrels.get(q.query_id, {})

    def answerable_queries(self) -> list[Query]:
        """判定データに適合文書がある（＝答えがコーパスに存在する）クエリ。"""
        return [q for q in self.queries if any(g >= 1 for g in self.qrels_for(q).values())]

    def retrieved_hits(self, q: Query, k: int = TOP_K) -> list[Hit]:
        return self.index.search(q.text, k=k)

    def gold_hits(self, q: Query, k: int = TOP_K) -> list[Hit]:
        """判定データから「本来渡すべきチャンク」を組み立てる（上限測定の入力）。

        完全適合（grade 2）の文書を優先し、無ければ部分適合（grade 1）に落とす。
        各文書からは、そのクエリに対して BM25 スコアが最も高いチャンクを1つ選ぶ。
        検索器の順位は使わないので、これは「検索が完璧だったとき」の入力になる。
        """
        cached = self._gold_cache.get((q.query_id, k))
        if cached is not None:
            return cached
        qr = self.qrels_for(q)
        gold_docs = {d for d, g in qr.items() if g >= 2} or {d for d, g in qr.items() if g >= 1}
        if not gold_docs:
            self._gold_cache[(q.query_id, k)] = []
            return []
        best: dict[str, Hit] = {}
        for h in self.index.search(q.text, k=len(self.index.chunks)):
            if h.doc_id in gold_docs and h.doc_id not in best:
                best[h.doc_id] = h
        for d in sorted(gold_docs):
            if d in best:
                continue
            chunks = self.chunks_by_doc.get(d, [])
            if chunks:  # 1語も一致しない文書は BM25 に出てこないので先頭チャンクで代用する
                c = chunks[0]
                best[d] = Hit(c.chunk_id, c.doc_id, 0.0, c.text, c.meta)
        hits = sorted(best.values(), key=lambda h: (-h.score, h.chunk_id))[:k]
        self._gold_cache[(q.query_id, k)] = hits
        return hits

    # --- トークン（忠実性の計算に使う）------------------------------------
    def tokens(self, text: str) -> list[str]:
        got = self._tok_cache.get(text)
        if got is None:
            got = tokenize(text)
            self._tok_cache[text] = got
        return got

    def overlap(self, text: str, sources: list[Hit]) -> float:
        """回答本文の内容語のうち、引用元にも現れる語の割合（0.0〜1.0）。"""
        if not sources:
            return 0.0
        ans = self.tokens(text)
        if not ans:
            return 0.0
        vocab: set[str] = set()
        for h in sources:
            vocab.update(self.tokens(h.text))
        return sum(1 for t in ans if t in vocab) / len(ans)


@dataclass
class Judgement:
    """1件の回答に対する自動検査の結果。合否を1つに潰さず、観点ごとに残す。"""

    answerable: bool          # モデルが「答えられる」と言ったか
    has_citation: bool        # 引用を1件でも出したか
    citations_valid: bool     # 引用がすべてコンテキストに実在したか
    invalid_citations: list[str]
    grounded: bool            # 引用先が判定データ上の適合文書か（根拠一致）
    faithfulness: float       # 回答本文と引用元の語の重なり（忠実性の代理）
    usable: bool              # 回答可能 かつ 引用が有効（採用してよいか）


def judge(bench: Bench, answer: Answer, hits: list[Hit], qr: dict[str, int]) -> Judgement:
    """回答を4つの観点で検査する。総合点にはしない（何を直すか分からなくなるため）。"""
    valid, invalid = verify_citations(answer, hits)
    by_id = {h.chunk_id: h for h in hits}
    cited = [by_id[c] for c in answer.citations if c in by_id]
    grounded = bool(cited) and all(qr.get(h.doc_id, 0) >= 1 for h in cited)
    return Judgement(
        answerable=answer.answerable,
        has_citation=bool(answer.citations),
        citations_valid=valid,
        invalid_citations=invalid,
        grounded=grounded,
        faithfulness=bench.overlap(answer.text, cited),
        usable=answer.answerable and valid,
    )


def classify_case(qr: dict[str, int], hits: list[Hit], j: Judgement) -> str:
    """失敗を3層に切り分ける。分類は仮説であって、上限測定で反証されうる。

    1. 適合文書がコーパスに無い → コーパス起因（回答不能と答えるのが正しい挙動）
       ただし答えてしまったら、直すのは生成側（回答不能の判定）
    2. 適合文書がコンテキストに届いていない → 検索起因
    3. 届いているのに使えない回答になった → 生成起因
    """
    if not any(g >= 1 for g in qr.values()):
        return LAYER_CORPUS if not j.answerable else LAYER_GENERATION
    if j.usable and j.grounded:
        return LAYER_OK
    delivered = any(qr.get(h.doc_id, 0) >= 1 for h in hits)
    return LAYER_GENERATION if delivered else LAYER_RETRIEVAL


@dataclass
class Case:
    """1クエリ分の記録。後から集計し直せるよう、判断の材料を全部残す。"""

    query_id: str
    query_type: str
    text: str
    layer: str
    judgement: Judgement
    n_hits: int
    relevant_in_context: int   # 適合（grade 1 以上）が何件届いたか
    gold_in_context: int       # 完全適合（grade 2）が何件届いたか
    extras: dict = field(default_factory=dict)


def collect_cases(bench: Bench, client, queries: list[Query] | None = None,
                  k: int = TOP_K, gold: bool = False) -> list[Case]:
    """全クエリを回して Case の一覧にする。gold=True で上限測定になる。"""
    out: list[Case] = []
    for q in (bench.queries if queries is None else queries):
        hits = bench.gold_hits(q, k) if gold else bench.retrieved_hits(q, k)
        qr = bench.qrels_for(q)
        ans = answer_with_citations(client, q.text, hits, max_chars=MAX_CHARS)
        j = judge(bench, ans, hits, qr)
        out.append(Case(
            query_id=q.query_id, query_type=q.type, text=q.text,
            layer=classify_case(qr, hits, j), judgement=j, n_hits=len(hits),
            relevant_in_context=sum(1 for h in hits if qr.get(h.doc_id, 0) >= 1),
            gold_in_context=sum(1 for h in hits if qr.get(h.doc_id, 0) >= 2),
        ))
    return out


def layer_counts(cases: list[Case]) -> dict[str, int]:
    counts = {layer: 0 for layer in LAYERS}
    for c in cases:
        counts[c.layer] = counts.get(c.layer, 0) + 1
    return counts


def pearson(xs: list[float], ys: list[float]) -> float:
    """相関係数。片方が 0/1 のときは点双列相関になる（式は同じ）。"""
    n = len(xs)
    if n < 2 or n != len(ys):
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:  # 片方が全部同じ値だと相関は定義できない
        return 0.0
    return cov / (vx ** 0.5 * vy ** 0.5)
