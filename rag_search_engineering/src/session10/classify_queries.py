#!/usr/bin/env python3
"""クエリを型に分類し、正解の型（corpus/queries.jsonl の type）と突き合わせる。

    python src/session10/classify_queries.py

分類そのものより「ルールの順序が結果を決める」ことを見るのが目的。
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from query_lab import classify, confusion, print_confusion  # noqa: E402

from ragkit.corpus import load_queries  # noqa: E402

# multi_condition を temporal より先に見る順序（＝わざと壊した順序）
SWAPPED_ORDER = ("multi_condition", "temporal", "abbrev", "keyword")


def main() -> None:
    queries = load_queries()

    print(f"=== クエリ分類（ルールベース / {len(queries)}件）===")
    print_confusion(confusion(queries))

    answerable = [q for q in queries if q.type != "unanswerable"]
    hit = sum(1 for q in answerable if classify(q.text) == q.type)
    print(f"\n回答可能な{len(answerable)}件の正解率: {hit}/{len(answerable)}")

    unans = Counter(classify(q.text) for q in queries if q.type == "unanswerable")
    print(f"回答不能の内訳: {dict(unans)}")
    print("  -> クエリ文だけを見ても「コーパスに答えがあるか」は分からない（セッション11の主題）")

    print(f"\n=== ルールの順序を入れ替える（{SWAPPED_ORDER[0]} を {SWAPPED_ORDER[1]} より先に見る）===")
    changed = [q for q in queries if classify(q.text, SWAPPED_ORDER) != classify(q.text)]
    print(f"化けたクエリ: {len(changed)}件")
    for q in changed:
        print(f"  {q.query_id} {q.type} -> {classify(q.text, SWAPPED_ORDER)}  {q.text}")
    print("  -> 「最新の規程では何と定められているか」の『何と』が並列パターンに当たっている")


if __name__ == "__main__":
    main()
