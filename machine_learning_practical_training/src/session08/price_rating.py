"""比較と関係を見る ― 箱ひげ図、散布図、そして「集約してから描く」。"""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from common import CATEGORY_ORDER, load_books, load_rated_reviews, save_fig

BAND_LABELS = ["Q1（安）", "Q2", "Q3", "Q4（高）"]


def main() -> None:
    # 1. 箱ひげ図：グループごとの「位置」と「広がり」を並べて比べる
    books = load_books()
    groups = [books.loc[books["category"] == category, "price"].to_numpy() for category in CATEGORY_ORDER]
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    ax.boxplot(groups, tick_labels=CATEGORY_ORDER, showmeans=True)
    ax.set_title("カテゴリ別の価格の分布（箱ひげ図・三角の印は平均）")
    ax.set_ylabel("価格（円）")
    save_fig(fig, "s08_price_box.png")

    # 2. 散布図：14,169 点をそのまま描くと重なって読めない
    reviews = load_rated_reviews()
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.4))
    axes[0].scatter(reviews["price"], reviews["rating"], s=6, alpha=0.03, color="#4c78a8")
    axes[0].set_title("散布図（14,169 点が重なる）")
    axes[0].set_xlabel("価格（円）")
    axes[0].set_ylabel("星")
    axes[0].set_ylim(0.5, 5.5)

    # 3. 価格を人数が同じ 4 つのグループに分け、平均の星を棒グラフにする
    reviews["価格帯"] = pd.qcut(reviews["price"], 4, labels=BAND_LABELS)
    band_mean = reviews.groupby("価格帯", observed=True)["rating"].mean()
    print("\n■ 価格を 4 分位に分けたときの平均の星")
    for band, value in band_mean.items():
        print(f"{band}: {value:.4f}")

    axes[1].bar(BAND_LABELS, band_mean.to_numpy(), color="#f58518")
    axes[1].set_ylim(1, 5)  # 星は 1〜5 の尺度。尺度の全体を見せる
    axes[1].set_title("価格帯ごとの平均の星（集約してから描く）")
    axes[1].set_xlabel("価格帯（4 分位）")
    axes[1].set_ylabel("平均の星")
    fig.suptitle("点が重なって読めないときは、集約してから描く")
    save_fig(fig, "s08_price_rating.png")


if __name__ == "__main__":
    main()
