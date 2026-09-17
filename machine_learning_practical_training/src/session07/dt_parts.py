"""dt アクセサで年・月・曜日を取り出し、年別・曜日別に数える。

使い方:
    docker compose exec lab python src/session07/dt_parts.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # 画面を持たないコンテナ内で図を PNG として保存するための設定
import matplotlib.pyplot as plt

from common import OUT_DIR, WEEKDAY_JA, load_valid_orders, make_toy


def main() -> None:
    # 1. 6 件の練習用データで dt アクセサの返り値を確かめる
    toy = make_toy()
    toy["year"] = toy["ordered_at"].dt.year
    toy["month"] = toy["ordered_at"].dt.month
    toy["day"] = toy["ordered_at"].dt.day
    toy["hour"] = toy["ordered_at"].dt.hour
    toy["dow"] = toy["ordered_at"].dt.dayofweek  # 月曜 = 0 ... 日曜 = 6
    toy["dow_ja"] = toy["dow"].map(lambda i: WEEKDAY_JA[i])
    toy["date"] = toy["ordered_at"].dt.normalize()  # 時刻を 00:00 に切り落とす
    toy["ym"] = toy["ordered_at"].dt.to_period("M")  # 年と月をひとまとめにした型

    print("■ 練習用データ 6 件を日時の部品に分解する")
    for row in toy.itertuples():
        print(
            f"{row.ordered_at:%Y-%m-%d %H:%M}  "
            f"{row.year} 年 {row.month} 月 {row.day} 日 {row.hour} 時  "
            f"曜日={row.dow}({row.dow_ja})  date={row.date:%Y-%m-%d}  ym={row.ym}"
        )

    # 2. 実データを年ごとに数える（顧客が積み上がるので右肩上がりになる）
    valid = load_valid_orders()
    by_year = valid["ordered_at"].dt.year.value_counts().sort_index()
    print("\n■ 年別の有効注文件数")
    for year, count in by_year.items():
        print(f"{year} 年 : {count:>6,} 件")

    # 3. 曜日ごとに数える（月曜 = 0 の順に並べる）
    by_dow = valid["ordered_at"].dt.dayofweek.value_counts().sort_index()
    spread = int(by_dow.max() - by_dow.min())
    print("\n■ 曜日別の有効注文件数")
    for dow, count in by_dow.items():
        print(f"{WEEKDAY_JA[dow]} : {count:>6,} 件")
    print(f"最小 {by_dow.min():,} 件 / 最大 {by_dow.max():,} 件 / 差 {spread:,} 件")
    print(f"平均 {round(float(by_dow.mean())):,} 件（差は平均の {spread / by_dow.mean():.1%}）")

    # 4. 曜日別の棒グラフを保存する（0 から描いて差の小ささをそのまま見せる）
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(5.5, 3.2))
    ax.bar([WEEKDAY_JA[i] for i in by_dow.index], by_dow.to_numpy(), color="#4c78a8")
    ax.set_title("曜日別の有効注文件数（2024-01-09 〜 2026-09-01）")
    ax.set_xlabel("曜日")
    ax.set_ylabel("件数")
    ax.set_ylim(0, 10000)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "s07_dow_orders.png", dpi=100)
    plt.close(fig)
    print("\n図を保存しました: outputs/s07_dow_orders.png")


if __name__ == "__main__":
    main()
