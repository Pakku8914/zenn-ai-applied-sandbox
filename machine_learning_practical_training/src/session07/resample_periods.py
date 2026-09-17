"""resample で日次・週次・月次に集計し、端の期間が不完全になることを確かめる。

使い方:
    docker compose exec lab python src/session07/resample_periods.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import OUT_DIR, WEEKDAY_JA, load_valid_orders, make_toy


def main() -> None:
    # 1. 練習用データで区切り方を確かめる。resample は日時をインデックスにしてから呼ぶ
    toy = make_toy().set_index("ordered_at")
    daily_toy = toy["amount"].resample("D").sum()
    mean_toy = toy["amount"].resample("D").mean()

    print("■ 練習用データを日次に集計する（注文が無い日も行として作られる）")
    for ts, amount in daily_toy.items():
        print(f"{ts:%Y-%m-%d}({WEEKDAY_JA[ts.dayofweek]}) : {amount:>6,} 円")
    print(f"件数 : {toy['amount'].resample('D').size().tolist()}")
    print(f"空の日（2026-08-26）: sum = {int(daily_toy.loc['2026-08-26'])} / mean = {mean_toy.loc['2026-08-26']}")

    print("\n■ 週次（W は日曜終わり）")
    for ts, amount in toy["amount"].resample("W").sum().items():
        print(f"{ts:%Y-%m-%d} まで : {amount:>6,} 円")

    print("\n■ 月次（ME は月末）")
    for ts, amount in toy["amount"].resample("ME").sum().items():
        print(f"{ts:%Y-%m-%d} まで : {amount:>6,} 円")

    # 2. 実データ。resample は並べ替えた日時インデックスの上で使う
    valid = load_valid_orders()
    series = valid.set_index("ordered_at")["amount"].sort_index()
    daily = series.resample("D").sum()
    weekly = series.resample("W").sum()
    monthly = series.resample("ME").sum().round().astype("int64")

    print(f"\n■ 有効注文 {len(valid):,} 件を期間ごとに集計する")
    print(f"日次 : {len(daily)} 行")
    print(f"週次 : {len(weekly)} 行（最初のラベル {weekly.index[0]:%Y-%m-%d} / 最後のラベル {weekly.index[-1]:%Y-%m-%d}）")
    print(f"月次 : {len(monthly)} 行")
    print(f"売上合計 : {int(round(series.sum())):,} 円")
    print(f"最大の月 : {monthly.idxmax():%Y-%m} の {monthly.max():,} 円")
    print(f"最小の月 : {monthly.idxmin():%Y-%m} の {monthly.min():,} 円")

    # 3. 末尾の月は「まだ終わっていない期間」なので、他の月と比べてはいけない
    last_days = valid.loc[valid["ordered_at"] >= "2026-09-01", "ordered_at"].dt.normalize().nunique()
    print(f"末尾の月 : {monthly.index[-1]:%Y-%m} の {monthly.iloc[-1]:,} 円（この月に含まれる日数 : {last_days} 日）")

    # 4. 月次売上の棒グラフ。末尾の 1 本だけ色を変えて「不完全な期間」であることを示す
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    colors = ["#4c78a8"] * len(monthly)
    colors[-1] = "#d62728"
    fig, ax = plt.subplots(figsize=(9, 3.4))
    ax.bar([f"{ts:%Y-%m}" for ts in monthly.index], monthly.to_numpy() / 10_000, color=colors)
    ax.set_title("月次の売上（赤い最後の月は 1 日分しか入っていない）")
    ax.set_xlabel("年月")
    ax.set_ylabel("売上（万円）")
    ax.tick_params(axis="x", rotation=90, labelsize=7)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "s07_monthly_revenue.png", dpi=110)
    plt.close(fig)
    print("\n図を保存しました: outputs/s07_monthly_revenue.png")


if __name__ == "__main__":
    main()
