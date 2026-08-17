#!/usr/bin/env python3
"""セッション8：RRF の候補数と rrf_k を振る。

つまみは2つあるが、効き方の大きさがまるで違うことを見るためのスクリプト。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ragkit.eval import evaluate  # noqa: E402

from compare_fusion import build  # noqa: E402
from fuse import FusionRetriever, my_rrf_fuse  # noqa: E402

K = 10


def main() -> None:
    lex, dense, queries, qrels = build()
    print("=== RRF：候補数と rrf_k を振る（fixed(400/80) / k=10 / 110クエリ）===")
    for candidates in (10, 20, 50):
        for rrf_k in (10, 60):
            r = FusionRetriever([lex, dense], candidates=candidates,
                                fuse=my_rrf_fuse, rrf_k=rrf_k)
            rep = evaluate(r, queries, qrels, k=K)
            label = f"cand={candidates} rrf_k={rrf_k}"
            print(f"{label:<24}Recall@{K}={rep.macro['recall']:.3f} "
                  f"nDCG@{K}={rep.macro['ndcg']:.3f} MRR={rep.macro['mrr']:.3f}")


if __name__ == "__main__":
    main()
