"""Figure（台紙）と Axes（1 枚の絵）の関係を確かめる。"""

from __future__ import annotations

import matplotlib.pyplot as plt

from common import load_reviews, save_fig


def main() -> None:
    reviews = load_reviews()
    counts = reviews["rating"].value_counts().sort_index()

    # 1 枚の Figure（台紙）に 2 つの Axes（絵）を横に並べる
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.2))
    print("■ Figure と Axes の関係")
    print(f"Figure の型: {type(fig).__name__}")
    print(f"axes の型: {type(axes).__name__}（要素数 {axes.size}）")
    print(f"axes[0] の型: {type(axes[0]).__name__}")

    # 左の絵：星ごとの件数（数えられる値なので棒グラフ）
    axes[0].bar([int(star) for star in counts.index], counts.to_numpy(), color="#4c78a8")
    axes[0].set_title("星ごとのレビュー件数")
    axes[0].set_xlabel("星の数")
    axes[0].set_ylabel("件数")

    # 右の絵：レビュー本文の長さ（連続値なのでヒストグラム）
    axes[1].hist(reviews["body_length"], bins=60, color="#54a24b")
    axes[1].set_title("レビュー本文の長さの分布")
    axes[1].set_xlabel("本文の長さ（文字）")
    axes[1].set_ylabel("件数")

    fig.suptitle("Figure は台紙、Axes は 1 枚 1 枚の絵")
    save_fig(fig, "s08_figure_axes.png")


if __name__ == "__main__":
    main()
