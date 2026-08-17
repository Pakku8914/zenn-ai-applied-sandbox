#!/usr/bin/env python3
"""セッション8：z-score 融合を min-max と比べる。

「z-score なら外れ値に強い」という通説を、実データと toy の両方で確かめる。
あわせて「重み 0 にすればその検索器を無効化できる」という誤解も潰す。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ragkit.eval import evaluate  # noqa: E402

from compare_fusion import build, line  # noqa: E402
from fuse import FusionRetriever, my_minmax_fuse, zscore_fuse  # noqa: E402

K = 10


def main() -> None:
    lex, dense, queries, qrels = build()

    print("=== 正規化方式の比較（候補50・重み 1.0:1.0）===")
    for label, fuse in (("minmax(1.0:1.0)", my_minmax_fuse), ("zscore(1.0:1.0)", zscore_fuse)):
        r = FusionRetriever([lex, dense], candidates=50, fuse=fuse, weights=[1.0, 1.0])
        line(label, evaluate(r, queries, qrels, k=K))

    print("\n=== 重み 0 は無効化ではない ===")
    q = queries[0].text
    lists = [lex.search(q, k=50), dense.search(q, k=50)]
    only_dense = {h.chunk_id for h in lists[1]} - {h.chunk_id for h in lists[0]}
    fused = my_minmax_fuse(lists, weights=[1.0, 0.0], k=50)
    left = [h.chunk_id for h in fused if h.chunk_id in only_dense]
    print(f"  クエリ: {q}")
    print(f"  dense 側にしか無いチャンク: {len(only_dense)} 件")
    print(f"  重み 0 でも統合結果に残っている数: {len(left)} 件（スコア 0 の塊になる）")
    print("  -> 本当に外したいなら hit_lists からリストごと外す")


if __name__ == "__main__":
    main()
