#!/usr/bin/env python3
"""A/B と段階リリース：トラフィックの分け方と、少数サンプルの危険。

    python src/session16/ab_split.py
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import bucket, tail_prob  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.corpus import load_queries  # noqa: E402

USERS = [f"U-{i:02d}" for i in range(1, 11)]


def main() -> None:
    queries = [q for q in load_queries() if q.type != "unanswerable"]

    print(f"=== 1. クエリ {len(queries)} 件を 50:50 に分ける ===")
    assigned = Counter(bucket(q.query_id) for q in queries)
    print(f"  A（現行）{assigned['A']} 件 / B（新方式）{assigned['B']} 件")
    print("  ちょうど半分にはならない。ハッシュで分けるとはそういうこと")

    print("\n=== 2. 決定性：同じキーは何度引いても同じ群 ===")
    stable = all(bucket(q.query_id) == bucket(q.query_id) for q in queries for _ in range(3))
    print(f"  3回引いて全件同じ群だったか: {stable}")
    changed = sum(1 for q in queries if bucket(q.query_id) != bucket(q.query_id, salt="s16-2"))
    print(f"  salt を変えると割り当てが変わる件数: {changed} / {len(queries)}")
    print("  実験をやり直すときは salt を変える（同じ人が同じ群に固定され続けるのを避ける）")

    print("\n=== 3. 段階リリース：B に回す割合を上げていく ===")
    print("  割合   B に入るクエリ数")
    for ratio in (1, 5, 10, 50, 100):
        n_b = sum(1 for q in queries if bucket(q.query_id, ratio=ratio) == "B")
        print(f"  {ratio:>3}%   {n_b:>4} 件")

    print("\n=== 4. 分割の単位：クエリ単位とユーザー単位 ===")
    by_user: dict[str, set[str]] = defaultdict(set)
    for i, q in enumerate(queries):
        by_user[USERS[i % len(USERS)]].add(bucket(q.query_id))
    mixed = sum(1 for arms in by_user.values() if len(arms) > 1)
    print(f"  クエリ単位で分けたとき、両方の群を体験したユーザー: {mixed} / {len(USERS)} 人")
    print(f"  ユーザー単位で分けたとき: 0 / {len(USERS)} 人（定義から必ず1群）")
    print("  同じ人が検索のたびに別の検索器に当たると、体験が不安定になり比較も濁る")

    print("\n=== 5. 少数サンプルの危険（互角の2つでも、これだけ勝ち越す）===")
    print("  試行  勝ち数  互角なのにこれ以上勝つ確率")
    for n, k in ((10, 7), (10, 8), (10, 9), (20, 14), (20, 15)):
        print(f"  {n:>4}  {k:>4}回以上   {tail_prob(n, k):.6f}")
    print("  10クエリで7勝しても、互角の可能性が 17% 残る。")
    print("  「10件見て良さそうだった」を判断根拠にしないこと")


if __name__ == "__main__":
    main()
