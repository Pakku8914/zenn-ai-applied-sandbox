#!/usr/bin/env python3
"""中間プロジェクト02：引用付き回答のパイプライン（製品側のコード）。

    docker compose exec app python src/mid02/pipeline.py

セッション9〜12 で作った部品を1本につなぐ。新しい検索方式は1つも増やしていない。
新しいのは「利用者に何を返すか・何を返さないか」を決める層である。

APIキーは不要（生成は合成カセット FixtureClient か StubClient で代用する）。

**凍結した条件**：チャンク fixed(400/80) / BM25 / 上位5件 / コンテキスト 2000字 /
`ragkit.answer.SYSTEM_PROMPT`。合成カセットの鍵はプロンプト全体の SHA-256 なので、
どれか1つでも変えると FixtureClient が KeyError になる（カセットの作り直しが要る）。

この pipeline.py は**測定の道具に依存しない**（`src/session12` を import しない）。
製品のコードが評価ハーネスに依存すると、評価をやめた瞬間に製品が動かなくなる。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # sandbox/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ragkit.answer import (  # noqa: E402
    Answer,
    answer_with_citations,
    build_context,
    verify_citations,
)
from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_queries  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.llm import FixtureClient, StubClient  # noqa: E402
from ragkit.models import Hit  # noqa: E402

# --- 凍結した条件（カセットの鍵に効く。変えたらカセットを作り直す）-------------
CHUNK_METHOD, CHUNK_SIZE, CHUNK_OVERLAP = "fixed", 400, 80
TOP_K = 5
MAX_CHARS = 2000

# --- 後処理の判定（verdict）。ok 以外はすべて利用者にそのまま出さない ----------
OK = "ok"
ABSTAINED = "abstained"                # モデル自身が回答不能と答えた（正しい棄却）
LOW_EVIDENCE = "low_evidence"          # 検索スコアが閾値未満（根拠が弱い）
UNPARSABLE = "unparsable"              # JSON として読めなかった
NO_CITATION = "no_citation"            # 引用が1件も無い
INVALID_CITATION = "invalid_citation"  # コンテキストに無い chunk_id を引用した
VERDICTS = (OK, ABSTAINED, LOW_EVIDENCE, UNPARSABLE, NO_CITATION, INVALID_CITATION)

FALLBACK_TEXT = (
    "この質問に答えられる根拠が社内文書の中に見つかりませんでした。"
    "ヘルプデスクの担当窓口へお問い合わせください。"
)


@dataclass(frozen=True)
class Result:
    """1リクエストの結末。落とした理由まで残す（後から集計し直せるように）。"""

    query_id: str
    query: str
    verdict: str
    text: str
    citations: tuple[str, ...]
    context_ids: tuple[str, ...]
    top_score: float
    invalid: tuple[str, ...] = ()

    @property
    def delivered(self) -> bool:
        """回答本文を利用者に出したか。ok 以外は定型文に差し替えている。"""
        return self.verdict == OK


def context_ids(hits: list[Hit], max_chars: int = MAX_CHARS, use_parent: bool = False) -> list[str]:
    """実際にコンテキストへ載った chunk_id だけを返す。

    `build_context` は入りきらないブロックが出た時点で打ち切るので、渡した候補と
    載った候補は一致しない。**引用検証の母集合をどちらにするかは設計判断**である。
    """
    ctx = build_context(hits, max_chars=max_chars, use_parent=use_parent)
    return [h.chunk_id for h in hits if f"[{h.chunk_id}]" in ctx]


def review(answer: Answer, pool: list[Hit], top_score: float,
           min_score: float | None = None,
           require_citation: bool = True) -> tuple[str, tuple[str, ...]]:
    """生成された回答を検査する。**判定の順序が結果を決める**ので順序も設計対象。

    1. モデルが自ら回答不能と言った → 正しい棄却（欠陥ではない）
       ただし本文が空なら JSON を読めなかった疑いとして unparsable に分ける
    2. 検索スコアが閾値未満 → 根拠が弱い（low_evidence）
    3. 引用が無い → no_citation
    4. 引用が母集合に無い → invalid_citation
    """
    if not answer.answerable:
        return (ABSTAINED if answer.text.strip() else UNPARSABLE), ()
    if min_score is not None and top_score < min_score:
        return LOW_EVIDENCE, ()
    if require_citation and not answer.citations:
        return NO_CITATION, ()
    _, invalid = verify_citations(answer, pool)
    if invalid:
        return INVALID_CITATION, tuple(invalid)
    return OK, ()


class AnswerPipeline:
    """検索 → コンテキスト → 生成 → 後処理 を1本にした製品側の入口。

    strict_citations=True にすると、引用の母集合を「渡した候補すべて」ではなく
    「実際にコンテキストへ載った候補」に絞る。厳しくなる方向にしか動かない。
    rerank_candidates を指定すると1段目の候補をリランクしてから上位を渡す（S09）。
    **リランクを入れると渡す本文が変わる＝カセットの鍵も変わる**ことに注意する。
    """

    def __init__(self, retriever, client, top_k: int = TOP_K, max_chars: int = MAX_CHARS,
                 min_score: float | None = None, strict_citations: bool = False,
                 rerank_candidates: int | None = None, fallback: str = FALLBACK_TEXT) -> None:
        self.retriever = retriever
        self.client = client
        self.top_k = top_k
        self.max_chars = max_chars
        self.min_score = min_score
        self.strict_citations = strict_citations
        self.rerank_candidates = rerank_candidates
        self.fallback = fallback

    def retrieve(self, query_text: str) -> list[Hit]:
        if not self.rerank_candidates:
            return self.retriever.search(query_text, k=self.top_k)
        from ragkit.rerank import RerankRetriever  # 重い import は使うときだけ

        staged = RerankRetriever(self.retriever, candidates=self.rerank_candidates)
        return staged.search(query_text, k=self.top_k)

    def run(self, query_text: str, query_id: str = "",
            hits: list[Hit] | None = None) -> Result:
        """1件処理する。hits を渡すと検索を飛ばせる（上限測定はこれを使う）。"""
        hits = self.retrieve(query_text) if hits is None else list(hits)
        ids = context_ids(hits, self.max_chars)
        answer = answer_with_citations(self.client, query_text, hits, max_chars=self.max_chars)
        pool = [h for h in hits if h.chunk_id in set(ids)] if self.strict_citations else hits
        top = hits[0].score if hits else float("-inf")
        verdict, invalid = review(answer, pool, top, self.min_score)
        if verdict == OK:
            return Result(query_id, query_text, OK, answer.text,
                          tuple(answer.citations), tuple(ids), top)
        # 落ちた回答は本文ごと差し替える。引用も残さない（根拠として使えないため）
        return Result(query_id, query_text, verdict, self.fallback, (), tuple(ids), top, invalid)


def verdict_counts(pipeline: AnswerPipeline, queries) -> dict[str, int]:
    """クエリ集合を通して判定の分布を数える。0 件の判定も欠かさず出す。"""
    counts = {v: 0 for v in VERDICTS}
    for q in queries:
        counts[pipeline.run(q.text, q.query_id).verdict] += 1
    return counts


def build_index() -> LexicalIndex:
    """合成カセットと同じ条件の索引（BM25 / fixed(400/80) / 673 チャンク）。"""
    chunks = chunk_all(load_docs(), CHUNK_METHOD, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
    return LexicalIndex().build(chunks)


def json_stub(payload: dict) -> StubClient:
    """決まった JSON を返すだけのクライアント（後処理だけを試すために使う）。"""
    return StubClient(default=json.dumps(payload, ensure_ascii=False))


def main() -> None:
    index = build_index()
    queries = load_queries()
    hits = index.search(queries[0].text, k=TOP_K)

    print("=== 1. 後処理の効きを1件で見る（StubClient・カセット不要）===")
    demos = [
        ("回答不能と自己申告", json_stub({"answerable": False,
                                          "answer": "見つかりませんでした。", "citations": []})),
        ("JSON として読めない", StubClient(default="はい、承知しました。")),
        ("引用が無い", json_stub({"answerable": True,
                                  "answer": "窓口へ申請してください。", "citations": []})),
        ("存在しない chunk_id", json_stub({"answerable": True, "answer": "規程のとおりです。",
                                           "citations": ["DOC-9999#001"]})),
        ("正しい引用", json_stub({"answerable": True, "answer": "規程のとおりです。",
                                  "citations": [hits[0].chunk_id]})),
    ]
    for label, client in demos:
        r = AnswerPipeline(index, client).run(queries[0].text, queries[0].query_id)
        print(f"  {label:<22} -> {r.verdict:<18} 利用者に出した: {r.delivered}")

    print("\n=== 2. 判定の分布（全120件・上位5件・コンテキスト2000字）===")
    for label, name in (("正常系 answers_v1       ", "answers_v1"),
                        ("異常系 answers_flawed_v1", "answers_flawed_v1")):
        counts = verdict_counts(AnswerPipeline(index, FixtureClient(name)), queries)
        shown = " ".join(f"{k}={v}" for k, v in counts.items() if v)
        print(f"  {label} {shown}  （止めた: {len(queries) - counts[OK]} 件）")

    print("\n後処理は「正しい答えを作る」道具ではない。間違った答えを出さないための道具である。")


if __name__ == "__main__":
    main()
