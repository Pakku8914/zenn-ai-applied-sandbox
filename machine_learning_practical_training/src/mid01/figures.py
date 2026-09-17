"""中間プロジェクト①の図 4 枚をまとめて描く。

    docker compose exec lab python src/mid01/figures.py

図はすべて outputs/ に保存します（この環境に画面はないので plt.show() は使わない）。
数値は analysis.py から受け取るだけで、この中では計算しません。
"""

from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.axes import Axes

from analysis import age_segment, age_share, category_summary, cross_revenue
from common import AGE_LABELS, CATEGORY_ORDER, save_fig, yen


def fig1_category() -> None:
    """図 1：カテゴリ別の売上と、1 注文あたりの平均金額を並べる。"""
    summary = category_summary()
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.0))

    left = axes[0].barh(summary.index.tolist(), summary["revenue"].to_numpy() / 1e6, color="#4c78a8")
    axes[0].bar_label(left, labels=[yen(v) for v in summary["revenue"]], padding=4, fontsize=8)
    axes[0].set_xlim(0, 75)  # 値ラベルが枠から出ないように余白を取る
    axes[0].set_title("図1a カテゴリ別の売上")
    axes[0].set_xlabel("売上（百万円）")

    right = axes[1].barh(summary.index.tolist(), summary["mean_amount"].to_numpy(), color="#f58518")
    axes[1].bar_label(
        right, labels=[f"{v:,.1f} 円" for v in summary["mean_amount"]], padding=4, fontsize=8
    )
    axes[1].set_xlim(0, 4800)
    axes[1].set_title("図1b 1 注文あたりの平均金額")
    axes[1].set_xlabel("1 注文あたりの平均金額（円）")

    fig.suptitle("カテゴリ別の売上の差は、注文の数ではなく 1 注文の大きさから来ている")
    save_fig(fig, "mid01_fig1_category.png")


def _heatmap(ax: Axes, table, title: str) -> None:
    """売上のクロス集計表をヒートマップとして描く（単位は百万円）。"""
    values = table.to_numpy() / 1e6
    ax.imshow(values, cmap="Blues", aspect="auto")
    ax.set_xticks(range(table.shape[1]), labels=table.columns.tolist(), rotation=30, ha="right")
    ax.set_yticks(range(table.shape[0]), labels=[str(name) for name in table.index])
    threshold = values.max() * 0.6  # 濃いセルだけ文字を白にする
    for row in range(table.shape[0]):
        for col in range(table.shape[1]):
            value = values[row, col]
            ax.text(
                col,
                row,
                f"{value:.1f}",
                ha="center",
                va="center",
                fontsize=8,
                color="white" if value > threshold else "black",
            )
    ax.set_title(title)


def fig2_crosstab() -> None:
    """図 2：年代 × カテゴリと流入経路 × カテゴリの売上（絶対額）。"""
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.2))
    _heatmap(axes[0], cross_revenue("年代"), "図2a 年代 × カテゴリの売上（百万円）")
    _heatmap(axes[1], cross_revenue("channel"), "図2b 流入経路 × カテゴリの売上（百万円）")
    fig.suptitle("絶対額でいちばん濃いセルは「人数の多い層 × 単価の高いカテゴリ」になる")
    save_fig(fig, "mid01_fig2_crosstab.png")


def fig3_age_share() -> None:
    """図 3：年代別のカテゴリ構成比。どのカテゴリもほぼ水平な線になる。"""
    share = age_share()
    tech = share["技術書"]
    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    for category in reversed(CATEGORY_ORDER):  # 上の線（技術書）から凡例に並べる
        ax.plot(AGE_LABELS, share[category].to_numpy(), marker="o", label=category)

    ax.set_ylim(0, 50)  # 0 から描く。差を大きく見せる軸の切り方をしない（セッション 8）
    ax.set_xlabel("年代")
    ax.set_ylabel("売上構成比（%）")
    ax.set_title(f"年代別のカテゴリ構成比（技術書は {tech.min():.1f}% 〜 {tech.max():.1f}% の幅しかない）")
    ax.legend(ncol=5, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.14))
    save_fig(fig, "mid01_fig3_age_share.png")


def fig4_segment_size() -> None:
    """図 4：年代別の顧客数と平均単価。差があるのは人数だけ。"""
    segment = age_segment()
    customers, price = segment["customers"], segment["mean_unit_price"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.0))

    bars = axes[0].bar(AGE_LABELS, customers.to_numpy(), color="#4c78a8")
    axes[0].bar_label(bars, labels=[f"{int(v):,} 人" for v in customers], padding=3, fontsize=8)
    axes[0].set_ylim(0, 2600)
    axes[0].set_title("図4a 年代別の顧客数（有効注文のある 7,629 人）")
    axes[0].set_ylabel("顧客数（人）")

    axes[1].bar(AGE_LABELS, price.to_numpy(), color="#f58518")
    axes[1].set_ylim(0, 2000)  # 0 から描くと「差が無い」ことが見える
    axes[1].set_title(f"図4b 年代別の平均単価（最小 {price.min():,.0f} 円 / 最大 {price.max():,.0f} 円）")
    axes[1].set_ylabel("注文 1 件あたりの単価の平均（円）")

    for ax in axes:
        ax.set_xlabel("年代")

    fig.suptitle("年代で大きく違うのは「人数」だけ。単価はそろっている")
    save_fig(fig, "mid01_fig4_segment_size.png")


def main() -> None:
    fig1_category()
    fig2_crosstab()
    fig3_age_share()
    fig4_segment_size()


if __name__ == "__main__":
    main()
