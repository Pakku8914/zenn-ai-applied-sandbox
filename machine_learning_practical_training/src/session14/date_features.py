"""日時の列を「部品」に分解して特徴量にする。

使い方:
    docker compose exec lab python src/session14/date_features.py
"""

from __future__ import annotations

import pandas as pd

from common import WEEKDAY_JA, add_datetime_features, cancel_rate, load_order_table


def make_toy() -> pd.DataFrame:
    """dt アクセサの結果を目で確かめるための 4 行の練習用データ。"""
    return pd.DataFrame(
        {
            "order_id": ["T1", "T2", "T3", "T4"],
            "ordered_at": pd.to_datetime(["2026-01-31", "2026-05-04", "2026-08-15", "2026-09-01"]),
        }
    )


def main() -> None:
    # 1. 練習用データで、どの列がどう作られるかを 1 行ずつ確かめる
    toy = add_datetime_features(make_toy())
    print("■ 練習用データ 4 件（基準日は 2026-09-01 に固定）")
    for row in toy.itertuples():
        print(
            f"{row.order_id} {row.ordered_at:%Y-%m-%d} → "
            f"weekday={row.weekday}({WEEKDAY_JA[row.weekday]}) month={row.month} "
            f"is_weekend={row.is_weekend} season={row.season} "
            f"基準日からの日数={row.days_to_reference}"
        )

    # 2. 実データに同じ関数を当てて、値の範囲が想定どおりかを確かめる
    df = add_datetime_features(load_order_table())
    print("\n■ 実データに当てたときの値の種類")
    print(f"weekday    : {df['weekday'].min()}〜{df['weekday'].max()} の {df['weekday'].nunique()} 種類")
    print(f"month      : {df['month'].min()}〜{df['month'].max()} の {df['month'].nunique()} 種類")
    flags = sorted(int(v) for v in df["is_weekend"].unique())  # numpy の値は int() に直してから表示する
    print(f"is_weekend : {flags} の {df['is_weekend'].nunique()} 種類")
    print(f"season     : {df['season'].nunique()} 種類（month の粗い要約なので、両方は入れない）")

    # 3. 週末フラグで分けたキャンセル率を、曜日別の率の帯と比べる
    by_weekday = df.groupby("weekday")["is_canceled"].mean()
    weekend_rate = cancel_rate(df, df["is_weekend"] == 1)
    weekday_rate = cancel_rate(df, df["is_weekend"] == 0)
    inside = bool(
        by_weekday.min() <= weekend_rate <= by_weekday.max()
        and by_weekday.min() <= weekday_rate <= by_weekday.max()
    )
    print("\n■ 週末フラグで分けたキャンセル率")
    print(f"週末 : {weekend_rate:.2%} / 平日 : {weekday_rate:.2%}")
    print(f"どちらも曜日別の率の帯（最小〜最大）の中に収まるか : {inside}")
    print("→ 曜日をまとめ直しても、新しい情報は出てきません")


if __name__ == "__main__":
    main()
