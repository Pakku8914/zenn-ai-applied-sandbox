"""誤解を招く図 ― 軸を切ると「差がある」ように見せられる。"""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from common import AGE_BINS, AGE_LABELS, load_books, load_customers, load_valid_orders, save_fig


def tech_share_by_age() -> pd.Series:
    """年代ごとに「技術書が売上に占める割合（%）」を返す。"""
    valid = load_valid_orders()
    df = valid.merge(load_books()[["book_id", "category"]], on="book_id", how="left").merge(
        load_customers()[["customer_id", "birth_year"]], on="customer_id", how="left"
    )
    df["age"] = 2026 - df["birth_year"]  # 年齢は基準年 2026 で固定する（本書の共通規約）
    df["年代"] = pd.cut(df["age"], bins=AGE_BINS, labels=AGE_LABELS)
    by_age = df.pivot_table(
        index="年代", columns="category", values="amount", aggfunc="sum", observed=True
    )
    # 行（年代）ごとに合計で割って構成比にする。丸めるのは表示のときだけ
    share = by_age.div(by_age.sum(axis=1), axis=0) * 100
    return share["技術書"]


def main() -> None:
    tech = tech_share_by_age()
    print("■ 年代別に見た「技術書が売上に占める割合」")
    print(f"年代の数: {len(tech)}")
    print(f"最小: {tech.min():.1f}%")
    print(f"最大: {tech.max():.1f}%")

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    axes[0].bar(AGE_LABELS, tech.to_numpy(), color="#e45756")
    axes[0].set_ylim(42.5, 44.5)  # 軸を切る＝差を誇張する
    axes[0].set_title("軸を切った図（差が大きく見える）")
    axes[1].bar(AGE_LABELS, tech.to_numpy(), color="#4c78a8")
    axes[1].set_ylim(0, 100)  # 構成比なので 0〜100% を見せる
    axes[1].set_title("0 から始めた図（ほぼ横ばい）")
    for ax in axes:
        ax.set_xlabel("年代")
        ax.set_ylabel("技術書の売上構成比（%）")
    fig.suptitle("同じ数値・同じ棒グラフ。違うのは縦軸だけ")
    save_fig(fig, "s08_misleading_axis.png")


if __name__ == "__main__":
    main()
