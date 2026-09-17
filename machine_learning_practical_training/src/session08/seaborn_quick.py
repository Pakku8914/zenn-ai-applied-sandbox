"""seaborn で分布と関係を素早く確認する。"""

from __future__ import annotations

import matplotlib.pyplot as plt
import seaborn as sns

from common import CATEGORY_ORDER, load_books, load_rated_reviews, save_fig


def main() -> None:
    # style だけでなく font も必ず指定する。省くと日本語が □（豆腐）になる
    sns.set_theme(style="whitegrid", font="Noto Sans CJK JP")
    print(f"seaborn のバージョン: {sns.__version__}")

    reviews = load_rated_reviews()
    books = load_books()

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    sns.histplot(data=reviews, x="body_length", bins=60, color="#4c78a8", ax=axes[0])
    axes[0].set_title("histplot：本文の長さの分布")
    axes[0].set_xlabel("本文の長さ（文字）")
    axes[0].set_ylabel("件数")

    sns.boxplot(data=books, x="category", y="price", order=CATEGORY_ORDER, ax=axes[1])
    axes[1].set_title("boxplot：カテゴリ別の価格")
    axes[1].set_xlabel("")
    axes[1].set_ylabel("価格（円）")

    fig.suptitle("seaborn は「列の名前を渡す」書き方で図を作る")
    save_fig(fig, "s08_seaborn_quick.png")


if __name__ == "__main__":
    main()
