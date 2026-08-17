#!/usr/bin/env python3
"""セッション8：クエリ型別の勝ち負けと、型別ルーティングの上限を出す。

平均だけを見ていると「ほぼ互角」に見える条件でも、型別に割ると
勝っている型と負けている型がはっきり分かれる。その差がハイブリッドの原資になる。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ragkit.eval import evaluate  # noqa: E402

from compare_fusion import build  # noqa: E402
from fuse import FusionRetriever, my_minmax_fuse, my_rrf_fuse  # noqa: E402

K = 10


def main() -> None:
    lex, dense, queries, qrels = build()
    conditions = [
        ("bm25", lex),
        ("dense", dense),
        ("rrf50", FusionRetriever([lex, dense], candidates=50, fuse=my_rrf_fuse, rrf_k=60)),
        ("mm1:1", FusionRetriever([lex, dense], candidates=50, fuse=my_minmax_fuse,
                                  weights=[1.0, 1.0])),
    ]
    reports = [(label, evaluate(r, queries, qrels, k=K)) for label, r in conditions]

    types = sorted(reports[0][1].by_type)
    print(f"=== クエリ型別 Recall@{K}（fixed(400/80) / 110クエリ）===")
    header = f"{'type':<16}{'n':>3}"
    for label, _ in reports:
        header += f"{label:>7}"
    print(header + f"{'best':>7}")

    total, n_all = 0.0, 0
    for t in types:
        row = f"{t:<16}{int(reports[0][1].by_type[t]['n_queries']):>3}"
        # 本書の実測表と突き合わせられるよう、表示と同じ3桁に丸めた値で比較する
        values = [round(rep.by_type[t]["recall"], 3) for _, rep in reports]
        for v in values:
            row += f"{v:>7.3f}"
        best = max(values)
        n = int(reports[0][1].by_type[t]["n_queries"])
        total += best * n
        n_all += n
        print(row + f"{best:>7.3f}")

    row = f"{'ALL':<16}{n_all:>3}"
    for _, rep in reports:
        row += f"{round(rep.macro['recall'], 3):>7.3f}"
    print(row + f"{total / n_all:>7.3f}")
    print(f"  -> 型ごとに最良の条件を選べたとしても Recall@{K} は {total / n_all:.3f} で頭打ち")


if __name__ == "__main__":
    main()
