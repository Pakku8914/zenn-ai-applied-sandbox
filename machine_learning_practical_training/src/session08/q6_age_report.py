"""問題6: 年代別のカテゴリ構成比を 100% 積み上げ棒で示し、レポート文まで書く。"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import (
    AGE_BINS,
    AGE_LABELS,
    CATEGORY_ORDER,
    load_books,
    load_customers,
    load_valid_orders,
    save_fig,
)


def share_by_age() -> pd.DataFrame:
    """年代 × カテゴリの売上構成比（%）を返す。"""
    valid = load_valid_orders()
    df = valid.merge(load_books()[["book_id", "category"]], on="book_id", how="left").merge(
        load_customers()[["customer_id", "birth_year"]], on="customer_id", how="left"
    )
    df["age"] = 2026 - df["birth_year"]  # 年齢は基準年 2026 で固定する
    df["年代"] = pd.cut(df["age"], bins=AGE_BINS, labels=AGE_LABELS)
    by_age = df.pivot_table(
        index="年代", columns="category", values="amount", aggfunc="sum", observed=True
    )
    # 行（年代）ごとの合計で割る。丸めるのは表示のときだけ
    return by_age[CATEGORY_ORDER].div(by_age.sum(axis=1), axis=0) * 100


def main() -> None:
    share = share_by_age()
    print(f"年代の数: {len(share)}")
    print("■ 年代ごとの構成比の合計（100.0% になるはず）")
    for age, total in share.sum(axis=1).items():
        print(f"{age}: {total:.1f}%")

    tech = share["技術書"]
    print(f"\n技術書の構成比: 最小 {tech.min():.1f}% / 最大 {tech.max():.1f}%")

    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    bottom = np.zeros(len(share))
    for category in CATEGORY_ORDER:
        values = share[category].to_numpy()
        axes[0].bar(AGE_LABELS, values, bottom=bottom, label=category)
        bottom = bottom + values  # 次の棒はここから積む
    axes[0].set_ylim(0, 100)
    axes[0].set_title("年代別のカテゴリ構成比（100% 積み上げ）")
    axes[0].set_ylabel("売上構成比（%）")
    axes[0].legend(fontsize=7, ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.12))

    axes[1].bar(AGE_LABELS, tech.to_numpy(), color="#4c78a8")
    axes[1].set_ylim(0, 100)  # 構成比なので 0〜100% を見せる
    axes[1].set_title("技術書だけを取り出した図（0 から始める）")
    axes[1].set_xlabel("年代")
    axes[1].set_ylabel("技術書の売上構成比（%）")

    save_fig(fig, "s08_q6_age_report.png")

    print("\n【レポート】")
    print("① 有効注文 57,869 件の売上を、顧客の年代（2026 年時点）× 書籍カテゴリで集計し、年代ごとの構成比にした図である。")
    print("② どの年代でも技術書が売上の 42.9〜44.3% を占め、カテゴリの構成はほとんど変わらない。")
    print("③ 差は 1.4 ポイントしかないため「年代で好みが違う」とは言えない。人数の少ない 10 代以下と 70 代以上は両端の年代にまとめている。")


if __name__ == "__main__":
    main()
