#!/usr/bin/env python3
"""セッション8：重みを「どこまで詰めてよいか」を、学習用と評価用に分けて確かめる。

110件しかないクエリ集合で重みを総当たりすると、選んだ重みは
そのクエリ集合の癖に合わせただけになる（過学習）。
分割して測り直すと、詰めた分がどれだけ残るかが分かる。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ragkit.eval import evaluate  # noqa: E402

from compare_fusion import build  # noqa: E402
from fuse import CachedLists, my_minmax_fuse  # noqa: E402

K = 10
WEIGHTS = [[1.0, 1.0], [0.3, 1.0], [0.5, 1.0], [1.0, 0.5], [1.0, 0.3]]


def split(queries, qrels):
    """回答可能なクエリを1件おきに分ける。並び順に依存せず型の比率が保たれる。"""
    answerable = [q for q in queries if any(g >= 1 for g in qrels.get(q.query_id, {}).values())]
    tune = [q for i, q in enumerate(answerable) if i % 2 == 0]
    holdout = [q for i, q in enumerate(answerable) if i % 2 == 1]
    return tune, holdout


def main() -> None:
    lex, dense, queries, qrels = build()
    tune, holdout = split(queries, qrels)
    print(f"=== 重みの探索（学習用 {len(tune)}件 / 評価用 {len(holdout)}件・min-max・候補50）===")

    cache = CachedLists([lex, dense], queries, candidates=50)
    rows = []
    for w in WEIGHTS:
        r = cache.retriever(my_minmax_fuse, weights=w)
        a = evaluate(r, tune, qrels, k=K).macro["recall"]
        b = evaluate(r, holdout, qrels, k=K).macro["recall"]
        rows.append((w, a, b))
        print(f"  w={w[0]}:{w[1]}   学習用 Recall@{K}={a:.3f}   評価用 Recall@{K}={b:.3f}")

    best_tune = max(rows, key=lambda r: r[1])
    best_hold = max(rows, key=lambda r: r[2])
    spread = max(r[1] for r in rows) - min(r[1] for r in rows)
    print(f"  学習用で最良: w={best_tune[0][0]}:{best_tune[0][1]}"
          f"（学習用 {best_tune[1]:.3f} / 同じ重みの評価用 {best_tune[2]:.3f}）")
    print(f"  評価用で最良: w={best_hold[0][0]}:{best_hold[0][1]}"
          f"（評価用 {best_hold[2]:.3f}）")
    print(f"  学習用の重み候補間の開き: {spread:.3f}")
    print(f"  汎化ギャップ（評価用の最良 - 学習用で選んだ重みの評価用）:"
          f" {best_hold[2] - best_tune[2]:.3f}")
    print("  -> 開きもギャップも小さいなら、それは重みの差ではなくクエリ集合の揺れ。")


if __name__ == "__main__":
    main()
