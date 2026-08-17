#!/usr/bin/env python3
"""セッション8：rrf_k が何を重く見る定数なのかを、逆転点を探して確かめる。

X: リスト1でだけ1位に出るチャンク（片方で圧勝）
Y: リスト1でもリスト2でも4位に出るチャンク（両方で中位）
rrf_k を大きくすると「票数」が、小さくすると「上位の順位差」が効く。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ragkit.models import Hit  # noqa: E402

from fuse import my_rrf_fuse  # noqa: E402

X, Y = "X-0001#001", "Y-0009#001"


def _h(chunk_id: str, score: float) -> Hit:
    return Hit(chunk_id, chunk_id.split("#")[0], score, "", {})


# X は1位（リスト1のみ）、Y は両方で4位。P と Q は両方に出る当て馬
LIST1 = [_h(X, 9.9), _h("P-0002#001", 8.0), _h("Q-0003#001", 7.0), _h(Y, 6.0)]
LIST2 = [_h("P-0002#001", 0.90), _h("Q-0003#001", 0.88), _h("R-0004#001", 0.80), _h(Y, 0.70)]


def main() -> None:
    print("=== rrf_k を振ったときの X（片方で1位）と Y（両方で4位）===")
    print(f"{'rrf_k':>5} {'X':>10} {'Y':>10}   勝者")
    flip = None
    prev = None
    for rrf_k in range(0, 21):
        fused = my_rrf_fuse([LIST1, LIST2], k=10, rrf_k=rrf_k)
        order = [h.chunk_id for h in fused]
        sx = 1.0 / (rrf_k + 1)
        sy = 2.0 / (rrf_k + 4)
        winner = X if order.index(X) < order.index(Y) else Y
        print(f"{rrf_k:>5} {sx:>10.6f} {sy:>10.6f}   {winner}")
        if prev is not None and winner != prev and flip is None:
            flip = rrf_k
        prev = winner
    print(f"  -> 実際に勝者が入れ替わるのは rrf_k={flip}。"
          " 1/(k+1) = 2/(k+4) の解 k=2 はちょうど同点で、chunk_id 昇順により X が残る。")


if __name__ == "__main__":
    main()
