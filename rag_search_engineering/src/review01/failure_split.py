#!/usr/bin/env python3
"""検索の失敗を「到達不足」と「順位不足」に分けて表示する。

  python src/review01/failure_split.py
      クエリ型別の内訳を表で出す

  python src/review01/failure_split.py --query "年休の手続きを知りたい"
      1クエリぶんの内訳を出す（切り分け手順書の一次切り分けで使う）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from review_lab import failure_split, print_split, zero_term_docs  # noqa: E402

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import hits_to_docs, recall_at_k  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

K = 10
POOL = 100


def main(argv: list[str]) -> int:
    docs = load_docs()
    queries = load_queries()
    qrels = load_qrels()
    index = LexicalIndex().build(chunk_all(docs, "fixed", size=400, overlap=80))

    if "--query" in argv:
        text = argv[argv.index("--query") + 1]
        match = next((q for q in queries if q.text == text), None)
        if match is None:
            print(f"判定データに無いクエリです: {text}")
            print("（適合文書が分からないと Recall は測れません。先に qrels を作ってください）")
            return 1
        qr = qrels.get(match.query_id, {})
        top = index.search(text, k=K)
        pool = index.search(text, k=POOL)
        r_k = recall_at_k(top, qr, K)
        r_pool = recall_at_k(pool, qr, POOL)
        print(f"{match.query_id} [{match.type}] {text}")
        print(f"  Recall@{K}    {r_k:.3f}")
        print(f"  到達@{POOL}   {r_pool:.3f}")
        print(f"  順位不足      {r_pool - r_k:.3f}  （候補には居るのに上位に来ていない）")
        print(f"  到達不足      {1.0 - r_pool:.3f}  （候補にすら入っていない）")
        print(f"  上位{K}件の文書: {hits_to_docs(top)}")
        relevant = [d for d, g in qr.items() if g >= 1]
        zero = zero_term_docs(text, relevant, {d.doc_id: d for d in docs})
        print(f"  適合文書 {len(relevant)} 件のうち、クエリの語を1つも含まない文書: {zero}")
        return 0

    print_split("bm25 / fixed(400/80)", failure_split(index, queries, qrels, k=K, pool=POOL),
                k=K, pool=POOL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
