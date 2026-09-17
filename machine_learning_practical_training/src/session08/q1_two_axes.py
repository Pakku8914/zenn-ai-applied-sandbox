"""問題1: Figure と Axes で 2 枚並べる ― 比較の図と分布の図。"""

from __future__ import annotations

import matplotlib.pyplot as plt

from common import CATEGORY_ORDER, load_books, save_fig


def main() -> None:
    books = load_books()
    # 並び順を固定する。図ごとに順番が変わると読み比べられない
    means = books.groupby("category")["price"].mean().reindex(CATEGORY_ORDER)

    print("■ カテゴリ別の平均価格（安い順）")
    for category, value in means.items():
        print(f"{category}: {value:,.0f} 円")

    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.2))

    # 左の絵：グループ間の大小を比べる（比較）
    axes[0].bar(CATEGORY_ORDER, means.to_numpy(), color="#4c78a8")
    axes[0].set_title("比較：カテゴリ別の平均価格")
    axes[0].set_xlabel("カテゴリ")
    axes[0].set_ylabel("平均価格（円）")

    # 右の絵：1 つの列の散らばりを見る（分布）
    axes[1].hist(books["price"], bins=40, color="#54a24b", edgecolor="white", linewidth=0.4)
    axes[1].set_title("分布：600 冊の価格")
    axes[1].set_xlabel("価格（円）")
    axes[1].set_ylabel("冊数")

    save_fig(fig, "s08_q1_two_axes.png")
    print("\n読み取り: 価格の分布の山は 1 つではなく複数ある（カテゴリごとに価格帯が違うため）")


if __name__ == "__main__":
    main()
