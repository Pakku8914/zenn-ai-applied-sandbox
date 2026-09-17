"""データドリフトを PSI で測る（本文 5 節）。

このデータには**ドリフトがありません**。それを実測で確かめるのがこの節の目的です。
監視の仕組みは、作っても発火しないのが正常な状態です。

使い方:
    docker compose exec lab python src/session28/drift_psi.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    PSI_ACT,
    PSI_WATCH,
    SPLIT_DATE,
    cancel_rates,
    psi_table,
    save_figure,
)

FIGURE_NAME = "s28_psi.png"


def draw(table, name: str = FIGURE_NAME) -> str:
    """4 列の PSI を棒にして、注意・要再学習の線を引く。"""
    fig, ax = plt.subplots(figsize=(8.0, 4.4))
    ax.bar(table["column"], table["psi"], color="#4c78a8", width=0.55)
    ax.axhline(PSI_WATCH, color="#f58518", linestyle="--", linewidth=1.2, label=f"注意（{PSI_WATCH}）")
    ax.axhline(PSI_ACT, color="#e45756", linestyle="--", linewidth=1.2, label=f"要再学習（{PSI_ACT}）")
    ax.set_ylim(0.0, 0.30)
    ax.set_ylabel("PSI")
    ax.set_title("実測の PSI は、注意の線にも届かない（＝ドリフトが無い）")
    for index, value in enumerate(table["psi"]):
        ax.text(index, value + 0.008, f"{value:.4f}", ha="center", fontsize=9)
    ax.legend(loc="upper left")
    return save_figure(fig, name)


def main() -> None:
    rates = cancel_rates()
    print("■ 1. 「学習したころ」と「いま」に分ける")
    print(f"境目: {SPLIT_DATE.date()}")
    print(
        f"前半: 注文 {rates['before_n']:,} 件 / 有効注文 {rates['before_valid']:,} 件"
        f" / キャンセル率 {rates['before_rate']:.4f}"
    )
    print(
        f"後半: 注文 {rates['after_n']:,} 件 / 有効注文 {rates['after_valid']:,} 件"
        f" / キャンセル率 {rates['after_rate']:.4f}"
    )
    print()

    table = psi_table()
    print("■ 2. 列ごとに PSI を測る（前半の 10 分位をビン境界にする）")
    print("列            |    PSI | 判定")
    for row in table.itertuples():
        print(f"{row.column:<14}| {row.psi:>6.4f} | {row.judgement}")
    worst = table.loc[table["psi"].idxmax()]
    print(f"いちばん大きい PSI: {worst['psi']:.4f}（{worst['column']}）")
    print()

    price = table.loc[table["column"] == "unit_price"].iloc[0]
    print("■ 3. 単価の平均も動いていない")
    print(f"前半の平均: {price['before_mean']:,.2f} 円")
    print(f"後半の平均: {price['after_mean']:,.2f} 円")
    print(f"差        : {price['after_mean'] - price['before_mean']:+,.2f} 円")
    print()

    print("■ 4. 判断")
    print(f"4 列すべてが {PSI_WATCH} 未満なので、このデータにはドリフトがありません。")
    print("監視は「発火しないのが正常」です。ここで安心して終わりにすると、")
    print("仕組みが本当に動くのかを確かめないまま運用に入ることになります（次の節へ）。")

    print(f"図を保存しました: outputs/{draw(table)}")


if __name__ == "__main__":
    main()
