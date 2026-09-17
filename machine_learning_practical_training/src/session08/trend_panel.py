"""推移を見る折れ線 ― 集計期間が不完全な月を帯と注記で示す。"""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from common import load_valid_orders, monthly_amount, save_fig


def main() -> None:
    valid = load_valid_orders()
    monthly = monthly_amount()
    print("■ 月次売上")
    print(f"有効注文: {len(valid):,} 件 / 売上合計: {int(round(valid['amount'].sum())):,} 円")
    print(f"最大: {monthly.idxmax():%Y-%m} / {int(round(monthly.max())):,} 円")
    print(f"最小: {monthly.idxmin():%Y-%m} / {int(round(monthly.min())):,} 円")
    print(f"末尾: {monthly.index[-1]:%Y-%m} / {int(round(monthly.iloc[-1])):,} 円")

    # 不完全な最後の月（2026-09 は 1 日分だけ）を帯で塗り、矢印で注記する
    fig, ax = plt.subplots(figsize=(9.5, 3.4))
    ax.plot(monthly.index, monthly.to_numpy() / 10_000, marker="o", markersize=3, color="#4c78a8")
    ax.axvspan(pd.Timestamp("2026-08-31"), monthly.index[-1], color="#e45756", alpha=0.15)
    ax.annotate(
        "1 日分しかない月",
        xy=(monthly.index[-1], monthly.iloc[-1] / 10_000),
        xytext=(-150, 40),
        textcoords="offset points",
        arrowprops={"arrowstyle": "->", "color": "#e45756"},
        color="#e45756",
    )
    ax.set_title("月次売上の推移（赤い帯は集計期間が不完全な月）")
    ax.set_xlabel("月")
    ax.set_ylabel("売上（万円）")
    save_fig(fig, "s08_monthly_trend.png")


if __name__ == "__main__":
    main()
