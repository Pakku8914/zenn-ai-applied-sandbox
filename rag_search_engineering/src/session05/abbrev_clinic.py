#!/usr/bin/env python3
"""「当たらない」を切り分けるための診断ツール（レキシカル検索版）。

1クエリについて、次の順に見ていく。上から順に潰すと原因が1つに絞れる。

  1. クエリがどう分割されたか（トークナイズ）
  2. 各語が索引に在るか（df）。df=0 なら語彙の不一致で、スコアリング以前の問題
  3. 適合文書が何位にいるか（順位の失敗か、到達の失敗か）

    python src/session05/abbrev_clinic.py Q-067
    python src/session05/abbrev_clinic.py --type abbrev   # 型ごとの一括診断
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import hits_to_docs, recall_at_k  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.tokenize_ja import tokenize  # noqa: E402


def diagnose(index: LexicalIndex, query, qrels_for_q: dict[str, int], corpus_text: str) -> None:
    relevant = sorted(d for d, g in qrels_for_q.items() if g >= 1)
    print(f"=== {query.query_id} ({query.type}) ===")
    print(f"クエリ: {query.text}")
    print(f"適合文書({len(relevant)}): {' '.join(relevant)}")

    print("--- クエリ語の内訳 ---")
    for term in tokenize(query.text, index.mode):
        df = len(index.postings.get(term, {}))
        mark = "  ← 索引に無い" if df == 0 else ""
        print(f"  {term}: df={df} idf={index._idf(term):.3f}"
              f" 原文中の出現={corpus_text.count(term)}{mark}")

    hits = index.search(query.text, k=10)
    print("--- 上位10件 ---")
    for rank, h in enumerate(hits, start=1):
        grade = qrels_for_q.get(h.doc_id, 0)
        print(f"  {rank:>2}. {h.chunk_id} score={h.score:.3f} grade={grade} "
              f"{h.meta['title'][:24]}")
    found = set(hits_to_docs(hits)) & set(relevant)
    print(f"上位10件に入った適合文書: {len(found)}/{len(relevant)} "
          f"(Recall@10={recall_at_k(hits, qrels_for_q, 10):.3f})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query_id", nargs="?", default="Q-067")
    ap.add_argument("--type", default=None, help="この型のクエリを一括診断する")
    ap.add_argument("--mode", default="morph")
    args = ap.parse_args()

    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    corpus_text = "\n".join(d.full_text for d in docs)
    index = LexicalIndex(mode=args.mode).build(chunk_all(docs, "fixed", size=400, overlap=80))

    if args.type:
        targets = [q for q in queries if q.type == args.type]
        zero = 0
        for q in targets:
            r = recall_at_k(index.search(q.text, k=10), qrels.get(q.query_id, {}), 10)
            zero += 1 if r == 0.0 else 0
            print(f"{q.query_id} Recall@10={r:.3f}  {q.text}")
        print(f"\n{args.type}: {len(targets)}件中 {zero}件が上位10件に適合文書ゼロ")
        return

    query = next(q for q in queries if q.query_id == args.query_id)
    diagnose(index, query, qrels.get(query.query_id, {}), corpus_text)


if __name__ == "__main__":
    main()
