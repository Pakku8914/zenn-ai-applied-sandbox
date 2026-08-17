#!/usr/bin/env python3
"""セッション8：スコアの尺度が違うと何が起きるかを、手で確かめられる例で見る。

実データではなく、暗算で追える小さな候補リストを使う。示したいのは3点。
  (1) 単純加算は BM25 の順位をなぞるだけになる
  (2) min-max 正規化は外れ値1件で順位が崩れる
  (3) RRF は順位しか見ないので崩れない
"""

from __future__ import annotations

import sys
from pathlib import Path
from statistics import mean, pstdev

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fuse import (  # noqa: E402
    TOY_DENSE,
    TOY_LEXICAL,
    TOY_LEXICAL_OUTLIER,
    my_minmax_fuse,
    my_rrf_fuse,
    naive_sum_fuse,
)


def show(hits, digits: int = 4) -> None:
    for i, h in enumerate(hits, start=1):
        print(f"  {i} {h.chunk_id}  {h.score:.{digits}f}")


def _gap(values: list[float], top: float, second: float, mode: str) -> float:
    """リスト内で top と second の正規化スコアがどれだけ離れているかを返す。"""
    if mode == "minmax":
        lo, hi = min(values), max(values)
        span = (hi - lo) or 1.0
        return (top - lo) / span - (second - lo) / span
    mu, sd = mean(values), pstdev(values) or 1.0
    return (top - mu) / sd - (second - mu) / sd


def main() -> None:
    print("=== 候補リスト（手計算できる小さな例）===")
    print("[BM25] score は非有界（0 以上で上限なし）")
    show(TOY_LEXICAL)
    print("[dense] score はコサイン類似度（-1 〜 1）")
    show(TOY_DENSE)

    print("\n=== (1) 単純加算：尺度の違うスコアをそのまま足す ===")
    show(naive_sum_fuse([TOY_LEXICAL, TOY_DENSE], k=10))
    print("  -> BM25 単体の順位と完全に同じ。dense の1位 DOC-0450#001 は最下位。")

    print("\n=== (2) RRF（rrf_k=60）：順位だけを使う ===")
    show(my_rrf_fuse([TOY_LEXICAL, TOY_DENSE], k=10, rrf_k=60), digits=6)
    print("  -> 両方に出た DOC-0331#001 が 2位に上がり、dense の1位も 3位に入る。")

    print("\n=== (3) min-max 正規化（重み 1.0:1.0）===")
    show(my_minmax_fuse([TOY_LEXICAL, TOY_DENSE], weights=[1.0, 1.0], k=10))
    print("  -> 各リストの1位が満点 1.0 をもらうので、両方の1位が並ぶ。")

    print("\n=== (4) BM25 側に外れ値を1件足す（DOC-0999#001 score=42.0）===")
    print("[min-max]")
    show(my_minmax_fuse([TOY_LEXICAL_OUTLIER, TOY_DENSE], weights=[1.0, 1.0], k=10))
    print("[RRF]")
    show(my_rrf_fuse([TOY_LEXICAL_OUTLIER, TOY_DENSE], k=10, rrf_k=60), digits=6)
    print("  -> min-max では DOC-0101#001 が 1位 -> 4位。RRF では 1位のまま。")

    print("\n=== (5) 正規化方式は外れ値に耐えるか"
          "（BM25 リスト内の DOC-0101#001 と DOC-0207#002 の差）===")
    before = [h.score for h in TOY_LEXICAL]
    after = [h.score for h in TOY_LEXICAL_OUTLIER]
    for mode in ("minmax", "zscore"):
        g0 = _gap(before, 18.0, 12.0, mode)
        g1 = _gap(after, 18.0, 12.0, mode)
        label = "min-max" if mode == "minmax" else "z-score"
        print(f"  {label}: {g0:.4f} -> {g1:.4f}  （外れ値追加後は {g1 / g0 * 100:.1f}%）")
    print("  -> どちらも外れ値に弱い。順位しか見ない RRF だけが影響を受けない。")


if __name__ == "__main__":
    main()
