"""問題5: seaborn で分布・比較・件数を 1 枚にまとめる。"""

from __future__ import annotations

import matplotlib.pyplot as plt
import seaborn as sns

from common import CATEGORY_ORDER, load_books, load_rated_reviews, save_fig


def main() -> None:
    # font を省くと日本語が □（豆腐）になる。style だけでなくフォントまで指定する
    sns.set_theme(style="whitegrid", font="Noto Sans CJK JP")
    print(f"seaborn のバージョン: {sns.__version__}")

    reviews = load_rated_reviews()
    books = load_books()

    counts = reviews["rating"].value_counts().sort_index()
    print("■ 星ごとの件数")
    for star, number in counts.items():
        print(f"星 {int(star)}: {int(number):,} 件")

    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6))

    sns.histplot(data=reviews, x="body_length", bins=60, color="#4c78a8", ax=axes[0])
    axes[0].set_title("分布：レビュー本文の長さ")
    axes[0].set_xlabel("本文の長さ（文字）")
    axes[0].set_ylabel("件数")

    sns.boxplot(data=books, x="category", y="price", order=CATEGORY_ORDER, ax=axes[1])
    axes[1].set_title("比較：カテゴリ別の価格")
    axes[1].set_xlabel("カテゴリ")
    axes[1].set_ylabel("価格（円）")

    sns.countplot(data=reviews, x="rating", color="#54a24b", ax=axes[2])
    axes[2].set_title("件数：星ごとのレビュー数")
    axes[2].set_xlabel("星の数")
    axes[2].set_ylabel("件数")

    save_fig(fig, "s08_q5_seaborn_panel.png")
    print("\n読み取り: 3 枚とも 1 行で描けるが、軸ラベルは列名がそのまま入るため日本語に直す必要がある")


if __name__ == "__main__":
    main()
