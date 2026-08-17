#!/usr/bin/env python3
"""問題1：尺度の違う2つのスコアを3通りの方法で統合し、順位の違いを見る。

BM25 のスコアは非有界（このコーパスでは十数）、コサイン類似度は -1〜1。
この2つを「そのまま足す」とどうなるかを、8件だけの小さなデータで確かめる。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fusion_lab import simple_sum_fuse  # noqa: E402

from ragkit.hybrid import minmax_fuse, rrf_fuse  # noqa: E402
from ragkit.models import Hit  # noqa: E402

# BM25 の上位5件（スコアは非有界。ここでは 11.50〜18.42）
BM25 = [("A", 18.42), ("B", 15.10), ("C", 12.30), ("D", 11.90), ("E", 11.50)]
# 密ベクトル検索の上位5件（コサイン類似度。ここでは 0.877〜0.912）
DENSE = [("F", 0.912), ("C", 0.905), ("G", 0.898), ("A", 0.881), ("H", 0.877)]


def to_hits(rows: list[tuple[str, float]]) -> list[Hit]:
    """(名前, スコア) の並びを Hit の列にする。名前はチャンクIDと文書IDに使う。"""
    return [Hit(f"{name}#001", name, score, "", {}) for name, score in rows]


def show(label: str, hits: list[Hit], digits: int = 3) -> None:
    body = "  ".join(f"{h.doc_id}:{h.score:.{digits}f}" for h in hits)
    print(f"{label:<22}{body}")


def main() -> None:
    lex, dense = to_hits(BM25), to_hits(DENSE)
    show("BM25（生スコア）", lex)
    show("密ベクトル（コサイン）", dense)
    print()
    show("① 単純加算", simple_sum_fuse([lex, dense], k=8))
    show("② RRF(rrf_k=60)", rrf_fuse([lex, dense], k=8, rrf_k=60), digits=5)
    show("③ min-max(1:1)", minmax_fuse([lex, dense], weights=[1.0, 1.0], k=8))
    print()
    print("順位だけを並べると違いが見えます。")
    for label, hits in [
        ("単純加算", simple_sum_fuse([lex, dense], k=8)),
        ("RRF", rrf_fuse([lex, dense], k=8, rrf_k=60)),
        ("min-max", minmax_fuse([lex, dense], weights=[1.0, 1.0], k=8)),
    ]:
        print(f"{label:<10}{' > '.join(h.doc_id for h in hits)}")


if __name__ == "__main__":
    main()
