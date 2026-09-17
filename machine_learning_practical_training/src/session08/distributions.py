"""分布を見る ― ヒストグラムのビンの数と、外れ値に潰された分布の直し方。"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

from common import load_orders, load_reviews, save_fig


def main() -> None:
    # 1. レビュー本文の長さ（連続値）をヒストグラムで見る
    reviews = load_reviews()
    length = reviews["body_length"]
    print("■ レビュー本文の長さ（14,467 件）")
    print(f"平均: {length.mean():.1f} 文字")
    print(f"中央値: {length.median():.0f} 文字")
    print(f"最大: {length.max():,} 文字")

    fig, axes = plt.subplots(1, 3, figsize=(11, 3.0))
    for ax, bins in zip(axes, [5, 30, 120]):
        ax.hist(length, bins=bins, color="#4c78a8", edgecolor="white", linewidth=0.4)
        ax.set_title(f"bins={bins}")
        ax.set_xlabel("本文の長さ（文字）")
    axes[0].set_ylabel("件数")
    fig.suptitle("同じデータでもビンの数で見え方が変わる")
    save_fig(fig, "s08_body_length_hist.png")

    # 2. 外れ値があると分布が右端に潰れる（注文数量 quantity）
    orders = load_orders()
    quantity = orders["quantity"]
    print("\n■ 注文数量 quantity（完全重複を落とした 60,031 行）")
    print(f"歪度（そのまま）: {quantity.skew():.4f}")
    print(f"歪度（log1p 変換後）: {np.log1p(quantity).skew():.4f}")
    print(f"15 以上の注文: {int((quantity >= 15).sum())} 件（最大 {int(quantity.max())}）")

    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.2))
    axes[0].hist(quantity, bins=40, color="#e45756")
    axes[0].set_title("そのまま（右に長い尾）")
    axes[0].set_xlabel("注文数量")
    axes[0].set_ylabel("件数")
    axes[1].hist(np.log1p(quantity), bins=40, color="#54a24b")
    axes[1].set_title("log1p で変換した後")
    axes[1].set_xlabel("log1p(注文数量)")
    axes[1].set_ylabel("件数")
    fig.suptitle("外れ値に引き伸ばされた軸は、対数に置き換えると読める")
    save_fig(fig, "s08_quantity_log.png")


if __name__ == "__main__":
    main()
