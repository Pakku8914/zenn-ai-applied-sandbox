"""問題1 の解答：日時から特徴量を作り、曜日に情報があるかを確かめる。

使い方:
    docker compose exec lab python src/session14/q1_date_features.py
"""

from __future__ import annotations

import pandas as pd

from common import WEEKDAY_JA, load_order_table

# 月から季節への対応表。3〜5 月を春として 3 か月ずつ区切る
SEASON_BY_MONTH = {
    3: "春", 4: "春", 5: "春",
    6: "夏", 7: "夏", 8: "夏",
    9: "秋", 10: "秋", 11: "秋",
    12: "冬", 1: "冬", 2: "冬",
}


def build_date_features(df: pd.DataFrame) -> pd.DataFrame:
    """ordered_at を曜日・月・週末フラグ・季節に分解して足す。"""
    out = df.copy()
    out["weekday"] = out["ordered_at"].dt.dayofweek  # 月曜 = 0 ... 日曜 = 6
    out["month"] = out["ordered_at"].dt.month
    out["is_weekend"] = (out["weekday"] >= 5).astype("int64")
    out["season"] = out["month"].map(SEASON_BY_MONTH)
    return out


def weekday_cancel_rate(df: pd.DataFrame) -> pd.Series:
    """曜日ごとのキャンセル率を月曜から順に返す。"""
    return df.groupby("weekday")["is_canceled"].mean()


def main() -> None:
    df = build_date_features(load_order_table())

    # 1. 作った列の値の範囲（想定どおりに作れているかの確認）
    print(f"母集団 : {len(df):,} 行")
    print(f"weekday {df['weekday'].nunique()} 種類 / month {df['month'].nunique()} 種類 / "
          f"is_weekend {df['is_weekend'].nunique()} 種類 / season {df['season'].nunique()} 種類")

    # 2. 曜日ごとのキャンセル率
    rates = weekday_cancel_rate(df)
    print("\n■ 曜日ごとのキャンセル率")
    for weekday, rate in rates.items():
        print(f"{WEEKDAY_JA[weekday]} : {rate:.2%}")
    spread = float(rates.max() - rates.min())
    print(f"最小 {rates.min():.2%} / 最大 {rates.max():.2%}")
    print(f"差が 0.5 ポイント未満か : {spread < 0.005}")

    # 3. 週末フラグにまとめ直しても、帯の中から出ないことを確認する
    by_flag = df.groupby("is_weekend")["is_canceled"].mean()
    inside = bool(rates.min() <= by_flag.min() and by_flag.max() <= rates.max())
    print(f"週末フラグ別の率が曜日別の帯の中に収まるか : {inside}")

    # 4. 季節ごとの件数（内訳は df["season"].value_counts() で見られる）
    #    件数の少ないグループの率は当てにならないので、大きさだけ先に確かめる
    season_counts = df["season"].value_counts()
    print(f"季節の数 : {len(season_counts)}")
    print(f"どの季節も 3,000 件を超えているか : {int(season_counts.min()) > 3000}")

    print("\n■ 判断")
    print("曜日ごとのキャンセル率は 0.5 ポイントも動かないので、曜日・週末フラグを特徴量に"
          "足しても予測の役には立たないと予想できます（実際に足した結果は問題4で確かめます）。")


if __name__ == "__main__":
    main()
