"""問題7: レポート用の 1 枚パネル（2 行 2 列）を作る。"""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from common import CATEGORY_ORDER, load_books, load_rated_reviews, load_reviews, monthly_amount, save_fig


def main() -> None:
    all_reviews = load_reviews()  # 分布は全 14,467 件で見る
    rated = load_rated_reviews()  # 星を使う図は 14,169 件（未入力の 298 件を除く）
    books = load_books()
    means = books.groupby("category")["price"].mean().reindex(CATEGORY_ORDER)
    monthly = monthly_amount()
    length = all_reviews["body_length"]

    print("■ パネルに載せる数値")
    print(f"本文の長さ: 平均 {length.mean():.1f} / 中央値 {length.median():.0f} / 最大 {length.max():,}")
    print(f"星が入っているレビュー: {len(rated):,} 件（未入力 {int(all_reviews['rating'].isna().sum())} 件を除く）")
    print(f"月次売上の最大: {monthly.idxmax():%Y-%m} / {int(round(monthly.max())):,} 円")
    for category, value in means.items():
        print(f"{category}: {value:,.0f} 円")

    fig, axes = plt.subplots(2, 2, figsize=(11, 6.5))
    axes[0, 0].hist(length, bins=60, color="#4c78a8")
    axes[0, 1].scatter(rated["body_length"], rated["rating"], s=5, alpha=0.03, color="#54a24b")
    axes[1, 0].plot(monthly.index, monthly.to_numpy() / 10_000, color="#e45756")
    axes[1, 0].axvspan(pd.Timestamp("2026-08-31"), monthly.index[-1], color="#e45756", alpha=0.15)
    axes[1, 1].barh(CATEGORY_ORDER, means.to_numpy(), color="#f58518")

    titles = [
        "分布：レビュー本文の長さ（全 14,467 件）",
        "関係：本文の長さと星（星のある 14,169 件）",
        "推移：月次売上（万円・帯は不完全な月）",
        "比較：カテゴリ別の平均価格（円）",
    ]
    for ax, title in zip(axes.flatten(), titles):  # flatten で 2 行 2 列を 1 列に並べ直す
        ax.set_title(title, fontsize=10)
    fig.suptitle("Bookstore データの 1 枚パネル（分布・関係・推移・比較）")
    save_fig(fig, "s08_q7_report_panel.png")

    print("\n【読み取り】")
    print("① 本文の長さは短い側に偏り、平均 83.7 文字に対して中央値は 66 文字（最大 1,331 文字）")
    print("② 本文が長いレビューほど星は低めだが、点が重なるため関係の強さは図だけでは判断できない")
    print("③ 月次売上は右肩上がりだが、末尾の 2026-09 は 1 日分しかないため他の月と比較できない")
    print("④ 平均価格は技術書 3,247 円と小説 939 円で 3 倍以上違う（ただし平均は分布の要約にすぎない）")
    print("次に確かめること: 売上の増加が顧客数の増加によるものか、1 人あたりの購入額も見る")


if __name__ == "__main__":
    main()
