#!/usr/bin/env python3
"""BM25 の2つの係数（tf の飽和・文書長の正規化）を数表で確かめる。

IDF は 1 とみなし、tf 側と長さ側の係数だけを取り出している。
コーパスに依存しない純粋な計算なので、どの環境でも同じ表が出る。

    python src/session05/bm25_factors.py
"""

from __future__ import annotations

K1S = (0.3, 1.2, 3.0)
TFS = (1, 2, 3, 5, 10, 20)
BS = (0.0, 0.5, 0.75, 1.0)
B_LABELS = ("b=0.0", "b=0.5", "b=0.75", "b=1.0")
RATIOS = (0.5, 1.0, 2.0, 4.0)


def tf_factor(tf: int, k1: float) -> float:
    """出現回数の効き方。tf を増やしても k1+1 で頭打ちになる（飽和）。"""
    return tf * (k1 + 1) / (tf + k1)


def len_factor(ratio: float, b: float, k1: float = 1.2, tf: int = 1) -> float:
    """文書長の効き方。ratio は dl/avgdl（平均の何倍の長さか）。"""
    return tf * (k1 + 1) / (tf + k1 * (1 - b + b * ratio))


def main() -> None:
    print("--- tf の効き方（文書長は平均と同じ・IDF=1 とみなす）---")
    print(f"{'tf':>6}" + "".join(f"{'k1=' + str(k):>9}" for k in K1S))
    for tf in TFS:
        print(f"{tf:>6}" + "".join(f"{tf_factor(tf, k):>9.4f}" for k in K1S))
    print("  上限(tf→∞): " + "  ".join(f"{k + 1:.4f}" for k in K1S))

    print("\n--- 文書長の効き方（tf=1・k1=1.2）---")
    print(f"{'dl/avgdl':>9}" + "".join(f"{lab:>9}" for lab in B_LABELS))
    for r in RATIOS:
        print(f"{r:>9.1f}" + "".join(f"{len_factor(r, b):>9.4f}" for b in BS))


if __name__ == "__main__":
    main()
