#!/usr/bin/env python3
"""横断復習03（セッション9〜12）の小道具。

新しい検索方式は増やしていない。ここにあるのは「渡ったかを数える・層に分ける・
上限を測る」だけである。打ち手を選ぶ前に、失敗がどの層で起きているかを数えるための道具。

  load_all              docs / queries / qrels / chunks（fixed 400/80）をまとめて読む
  bm25_index            合成カセットと同じ条件の BM25 索引（fixed(400/80)・morph）
  included_hits         build_context に実際に載ったヒットだけを返す
  has_gold_in_context   適合文書がコンテキストに載ったか（0/1）
  context_recall        「載った割合」を型別と ALL で集計する（生成層の入力の質）
  OracleRetriever       適合文書のチャンクだけを返す検索器（上限測定にだけ使う）
  classify_answer       1件の応答を4つの結末に仕分ける
  layer_split           回答可能クエリを「検索層 / 生成層 / 成功」に切り分ける
  abstention_check      回答不能クエリの結末を数える

**この章の検索条件は動かせない。** 合成カセットの鍵はプロンプト全体のハッシュなので、
チャンク方式・検索器・上位k件・コンテキスト上限・システムプロンプトのどれか1つでも
変えると FixtureClient が KeyError になる（その確認は cassette_guard.py で行う）。
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.answer import answer_with_citations, build_context, verify_citations  # noqa: E402
from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.models import Chunk, Hit  # noqa: E402

# 合成カセットを作ったときの条件。ここを変えるとカセットが無効になる
TOP_K = 5
MAX_CHARS = 2000

# 合成カセットが「答えるかどうか」を決めている適合度のしきい値。
# 層の判定もここにそろえる（そろえないと切り分けの表が簡単に嘘をつく）
GOLD_GRADE = 2

OUTCOMES = ("ok", "no_citation", "invalid_citation", "abstained")


# ---------------------------------------------------------------------------
# 1. 読み込み（S03 × S04 × S05）
# ---------------------------------------------------------------------------


def load_all():
    """docs / queries / qrels / chunks を読む。チャンクは fixed(400/80)・673 個。"""
    docs = load_docs()
    queries = load_queries()
    qrels = load_qrels()
    chunks = chunk_all(docs, "fixed", size=400, overlap=80)
    return docs, queries, qrels, chunks


def bm25_index(chunks: list[Chunk]) -> LexicalIndex:
    """合成カセットと同じ条件の索引（BM25・形態素・fixed(400/80)）。"""
    return LexicalIndex().build(chunks)


def answerable(queries, qrels) -> list:
    """適合文書が1件以上あるクエリ（判定データ側の定義）。"""
    return [q for q in queries if any(g >= 1 for g in qrels.get(q.query_id, {}).values())]


def unanswerable(queries, qrels) -> list:
    """適合文書が1件も無いクエリ。コーパスに答えが無いので、答えてはいけない。"""
    return [q for q in queries if not any(g >= 1 for g in qrels.get(q.query_id, {}).values())]


# ---------------------------------------------------------------------------
# 2. コンテキストに何が載ったか（S11 × S04）
# ---------------------------------------------------------------------------


def included_hits(hits: list[Hit], max_chars: int = MAX_CHARS,
                  use_parent: bool = False) -> list[Hit]:
    """build_context に実際に載ったヒットだけを返す。

    `build_context` は入りきらないブロックが出た時点で打ち切るので、載るのは
    **先頭から連続した分だけ**である。落ちた候補は引用できないし、生成も読めない。
    """
    ctx = build_context(hits, max_chars=max_chars, use_parent=use_parent)
    return [h for h in hits if f"[{h.chunk_id}]" in ctx]


def has_gold_in_context(hits: list[Hit], qr: dict[str, int], max_chars: int = MAX_CHARS,
                        use_parent: bool = False, min_grade: int = GOLD_GRADE) -> bool:
    """適合文書のチャンクがコンテキストに1件でも載ったか。"""
    return any(qr.get(h.doc_id, 0) >= min_grade
               for h in included_hits(hits, max_chars, use_parent))


def context_recall(retriever, queries, qrels, k: int = TOP_K, max_chars: int = MAX_CHARS,
                   use_parent: bool = False,
                   min_grade: int = GOLD_GRADE) -> dict[str, dict[str, float]]:
    """適合文書がコンテキストに載ったクエリの割合を、型別と ALL で返す。

    Recall@k が「上位k件に適合文書の何割が入ったか」なのに対して、こちらは
    「生成に渡した文字列の中に手がかりが1つでもあったか」を 0/1 で見る。
    **生成層の上限はここで決まる**（渡っていないものは、どんな LLM でも使えない）。
    """
    acc: dict[str, list[float]] = defaultdict(list)
    for q in queries:
        qr = qrels.get(q.query_id, {})
        if not any(g >= min_grade for g in qr.values()):
            continue
        hits = retriever.search(q.text, k=k)
        v = 1.0 if has_gold_in_context(hits, qr, max_chars, use_parent, min_grade) else 0.0
        acc[q.type].append(v)
        acc["ALL"].append(v)
    return {t: {"n": float(len(vs)), "rate": sum(vs) / len(vs)} for t, vs in acc.items()}


def mean_included(retriever, queries, k: int = TOP_K, max_chars: int = MAX_CHARS,
                  use_parent: bool = False) -> float:
    """1クエリあたり平均何件がコンテキストに載ったか。"""
    counts = [len(included_hits(retriever.search(q.text, k=k), max_chars, use_parent))
              for q in queries]
    return sum(counts) / len(counts) if counts else 0.0


class OracleRetriever:
    """判定データを見て、適合文書のチャンクだけを返す検索器。

    検索層の失敗をゼロにした世界を作るためだけの道具である。
    **評価に使ってはいけない**（答えを見て候補を組んでいるので当たって当然）。
    上限測定（正解チャンクを渡したら答えられるか）にだけ使う。
    """

    def __init__(self, chunks: list[Chunk], queries, qrels,
                 min_grade: int = GOLD_GRADE) -> None:
        self.by_doc: dict[str, list[Chunk]] = defaultdict(list)
        for c in chunks:
            self.by_doc[c.doc_id].append(c)
        self.qrels = qrels
        self.min_grade = min_grade
        self.qid_of = {q.text: q.query_id for q in queries}

    def search(self, query: str, k: int = 10, filters: dict | None = None) -> list[Hit]:
        qr = self.qrels.get(self.qid_of.get(query, ""), {})
        rows = sorted(((d, g) for d, g in qr.items() if g >= self.min_grade),
                      key=lambda kv: (-kv[1], kv[0]))
        hits: list[Hit] = []
        for doc_id, grade in rows:
            # 1文書につき先頭のチャンクだけを代表として渡す（同一文書で埋めない）
            for c in self.by_doc.get(doc_id, [])[:1]:
                hits.append(Hit(c.chunk_id, c.doc_id, float(grade), c.text, c.meta))
        return hits[:k]


# ---------------------------------------------------------------------------
# 3. 応答の結末（S11 × S12）
# ---------------------------------------------------------------------------


def classify_answer(ans, hits: list[Hit], max_chars: int = MAX_CHARS,
                    strict: bool = False) -> str:
    """1件の応答を4つの結末に仕分ける。上から順に判定する。

      abstained         回答不能と自己申告した
      no_citation       答えたが引用が無い
      invalid_citation  答えたが、突き合わせ先に無い chunk_id を引用した
      ok             答えて、引用がすべて突き合わせ先にあった

    strict=True にすると突き合わせ先を「候補の全件」から
    「コンテキストに実際に載った分だけ」に絞る。上限文字数で落ちた候補を引用した
    応答は、strict でだけ invalid_citation になる。
    """
    if not ans.answerable:
        return "abstained"
    if not ans.citations:
        return "no_citation"
    pool = included_hits(hits, max_chars) if strict else hits
    _, invalid = verify_citations(ans, pool)
    return "invalid_citation" if invalid else "ok"


def outcome_counts(index, client, queries, k: int = TOP_K, max_chars: int = MAX_CHARS,
                   strict: bool = False) -> dict[str, int]:
    """クエリ集合を通して、4つの結末の件数を数える。"""
    counts = {name: 0 for name in OUTCOMES}
    for q in queries:
        hits = index.search(q.text, k=k)
        ans = answer_with_citations(client, q.text, hits, max_chars=max_chars)
        counts[classify_answer(ans, hits, max_chars, strict=strict)] += 1
    return counts


def layer_split(index, client, queries, qrels, k: int = TOP_K, max_chars: int = MAX_CHARS,
                min_grade: int = GOLD_GRADE) -> dict[str, list[str]]:
    """回答可能クエリの結末を3層に切り分ける。

      retrieval   コンテキストに適合文書が1件も載っていない（検索層の失敗）
      generation  載っているのに、答えないか引用が壊れている（生成層の失敗）
      ok          載っていて、答えて、引用も有効

    コーパスに情報が無い層（回答不能クエリ）はここには来ない。
    そちらは abstention_check で別に数える。
    """
    out: dict[str, list[str]] = {"retrieval": [], "generation": [], "ok": []}
    for q in answerable(queries, qrels):
        qr = qrels[q.query_id]
        hits = index.search(q.text, k=k)
        ans = answer_with_citations(client, q.text, hits, max_chars=max_chars)
        outcome = classify_answer(ans, hits, max_chars)
        if not has_gold_in_context(hits, qr, max_chars, min_grade=min_grade):
            out["retrieval"].append(q.query_id)
        elif outcome != "ok":
            out["generation"].append(q.query_id)
        else:
            out["ok"].append(q.query_id)
    return out


def abstention_check(index, client, queries, qrels, k: int = TOP_K,
                     max_chars: int = MAX_CHARS) -> dict[str, int]:
    """回答不能クエリ（コーパスに答えが無いクエリ）の結末を数える。"""
    return outcome_counts(index, client, unanswerable(queries, qrels), k=k, max_chars=max_chars)


def print_layers(label: str, split: dict[str, list[str]], abst: dict[str, int]) -> None:
    total = sum(len(v) for v in split.values())
    print(f"[{label}] 回答可能 {total} 件")
    for name, jp in (("ok", "成功              "),
                     ("retrieval", "検索層の失敗      "),
                     ("generation", "生成層の失敗      ")):
        n = len(split[name])
        print(f"  {jp}: {n:>4} 件 ({n / total:.3f})" if total else f"  {jp}: 0 件")
    print(f"  回答不能クエリ    : 回答不能と判定 {abst['abstained']} 件 / "
          f"答えてしまった {sum(v for key, v in abst.items() if key != 'abstained')} 件")


def main() -> None:
    from ragkit.llm import FixtureClient

    _, queries, qrels, chunks = load_all()
    index = bm25_index(chunks)
    good = FixtureClient("answers_v1")

    split = layer_split(index, good, queries, qrels)
    abst = abstention_check(index, good, queries, qrels)
    print_layers("bm25 / fixed(400/80) / 上位5件 / 合成カセット answers_v1", split, abst)

    print("\n[コンテキストに適合文書が載った割合]")
    for label, ret, use_parent in (("bm25 上位5件", index, False),
                                   ("オラクル（上限）",
                                    OracleRetriever(chunks, queries, qrels), False)):
        rows = context_recall(ret, answerable(queries, qrels), qrels, use_parent=use_parent)
        print(f"  {label:<18} ALL {rows['ALL']['rate']:.3f} (n={int(rows['ALL']['n'])})  "
              + "  ".join(f"{t} {rows[t]['rate']:.3f}"
                          for t in sorted(rows) if t != "ALL"))


if __name__ == "__main__":
    main()
