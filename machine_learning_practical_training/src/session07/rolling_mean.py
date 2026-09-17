"""rolling で移動平均を計算し、日々のばらつきの裏にある傾向を読む。

使い方:
    docker compose exec lab python src/session07/rolling_mean.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import OUT_DIR, load_valid_orders, make_toy


def main() -> None:
    # 1. 8 日分の練習用データで窓の動きを確かめる
    toy_daily = make_toy().set_index("ordered_at")["amount"].resample("D").sum()
    window3 = toy_daily.rolling(3).mean()
    window3_min1 = toy_daily.rolling(3, min_periods=1).mean()
    centered = toy_daily.rolling(3, center=True).mean()

    print("■ 3 日移動平均（列 : 日付 / 売上 / rolling(3) / min_periods=1 / center=True）")
    for ts in toy_daily.index:
        print(
            f"{ts:%Y-%m-%d}{toy_daily[ts]:>8,}{window3[ts]:>12.1f}"
            f"{window3_min1[ts]:>15.1f}{centered[ts]:>13.1f}"
        )

    # 2. 実データの日次注文数と移動平均
    valid = load_valid_orders()
    daily_orders = valid.set_index("ordered_at").sort_index().resample("D").size()
    roll7 = daily_orders.rolling(7).mean()
    roll28 = daily_orders.rolling(28).mean()

    print("\n■ 有効注文の日次注文数")
    print(f"日次の行数             : {len(daily_orders)} 行")
    print(f"1 日あたりの平均注文数 : {daily_orders.mean():.2f} 件")
    print(f"1 日の最大注文数       : {int(daily_orders.max())} 件")
    print(f"7 日移動平均の NaN     : {int(roll7.isna().sum())} 行")
    print(f"28 日移動平均の NaN    : {int(roll28.isna().sum())} 行")

    # 3. 年ごとの 1 日平均。移動平均が上を向いている理由を数値でも確かめる
    by_year = daily_orders.groupby(daily_orders.index.year).agg(["size", "sum", "mean"])
    print("\n■ 年ごとの日数と 1 日平均")
    for year, row in by_year.iterrows():
        print(f"{year} 年 : {int(row['size'])} 日  1 日平均 {row['mean']:>6.2f} 件")

    # 4. 日次注文数と移動平均を重ねて描く
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 3.4))
    ax.plot(daily_orders.index, daily_orders.to_numpy(), color="#c7c7c7", linewidth=0.8, label="日次の注文数")
    ax.plot(roll7.index, roll7.to_numpy(), color="#4c78a8", linewidth=1.4, label="7 日移動平均")
    ax.plot(roll28.index, roll28.to_numpy(), color="#d62728", linewidth=1.6, label="28 日移動平均")
    ax.set_title("日次の注文数と移動平均")
    ax.set_xlabel("注文日")
    ax.set_ylabel("注文件数")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "s07_daily_orders_rolling.png", dpi=110)
    plt.close(fig)
    print("\n図を保存しました: outputs/s07_daily_orders_rolling.png")


if __name__ == "__main__":
    main()
