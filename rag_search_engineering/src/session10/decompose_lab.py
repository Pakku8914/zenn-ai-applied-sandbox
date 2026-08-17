#!/usr/bin/env python3
"""複数条件クエリをサブ質問に分け、結果を RRF で統合する。

    python src/session10/decompose_lab.py

分解は「1回の検索で2つの主題を同時に上位へ乗せる」という無理をやめて、
2回の検索に分けるだけの操作。検索回数は増えるが、LLM は1回も呼ばない。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from query_lab import MultiQueryRetriever, decompose, multi_query  # noqa: E402

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

TYPES = ("abbrev", "keyword", "multi_condition", "natural", "temporal")
REPORT_DIR = Path(__file__).resolve().parents[2] / "reports"


def main() -> None:
    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    index = LexicalIndex().build(chunk_all(docs, "fixed", size=400, overlap=80))

    print("=== 1. 分解の結果 ===")
    fired = [q for q in queries if len(decompose(q.text)) > 1]
    for q in fired:
        subs = decompose(q.text)
        print(f"{q.query_id} {q.text}")
        print(f"    -> {subs[0]} / {subs[1]}")
    print(f"分解が発火したクエリ: {len(fired)}件  型: {sorted({q.type for q in fired})}")

    print("\n=== 2. 分解しないクエリはそのまま1本で通す ===")
    for qid in ("Q-001", "Q-067"):
        q = next(x for x in queries if x.query_id == qid)
        print(f"{qid} {q.text} -> {decompose(q.text)}")

    router = MultiQueryRetriever(index, decompose, candidates=20)
    rep_base = evaluate(index, queries, qrels, k=10, label="bm25 / fixed")
    rep_dec = evaluate(router, queries, qrels, k=10, label="bm25 / fixed + クエリ分解")

    print("\n=== 3. 分解の効果（Recall@10 / fixed(400/80) / 110クエリ）===")
    print(f"{'type':<18}{'n':>5}{'base':>10}{'split':>10}{'diff':>10}")
    for t in TYPES:
        b, a = rep_base.by_type[t], rep_dec.by_type[t]
        print(f"{t:<18}{int(b['n_queries']):>5}{b['recall']:>10.3f}{a['recall']:>10.3f}"
              f"{a['recall'] - b['recall']:>+10.3f}")
    print(f"{'ALL':<18}{int(rep_base.macro['n_queries']):>5}"
          f"{rep_base.macro['recall']:>10.3f}{rep_dec.macro['recall']:>10.3f}"
          f"{rep_dec.macro['recall'] - rep_base.macro['recall']:>+10.3f}")
    print(f"検索の実行回数: {router.searches} 回（110クエリ中12件が2回検索したので 110 + 12）")
    print("LLM 呼び出し: 0 回")

    print("\n=== 4. ルールベースの多クエリ生成（言い換えを並べて投げる）===")
    for qid in ("Q-067", "Q-001"):
        q = next(x for x in queries if x.query_id == qid)
        print(f"{qid} {q.text}")
        for v in multi_query(q.text):
            print(f"    - {v}")

    rep_dec.to_json(REPORT_DIR / "s10_decompose.json")
    print("\n-> reports/s10_decompose.json")


if __name__ == "__main__":
    main()
