"""問題4 の解答: describe の count から rating の欠損件数を逆算する。

使い方:
    docker compose exec lab python src/session03/q4_rating_missing.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def main() -> None:
    reviews = pd.read_csv(DATA_DIR / "reviews.csv", parse_dates=["reviewed_at"])

    print("■ rating の describe")
    print(reviews["rating"].describe().round(4))

    rows = len(reviews)
    count = int(reviews["rating"].describe()["count"])
    print(f"\nrating の dtype   : {reviews['rating'].dtype}")
    print(f"行数              : {rows}")
    print(f"describe の count : {count}")
    print(f"差（欠損の件数）  : {rows - count}")
    print(f"isna().sum()      : {int(reviews['rating'].isna().sum())}")
    print(f"一致しているか    : {rows - count == int(reviews['rating'].isna().sum())}")

    # 平均は欠損を自動的に除いて計算される（分母は 14,169 件）
    print(f"\nmean()            : {reviews['rating'].mean():.4f}")
    print(f"dropna().mean()   : {reviews['rating'].dropna().mean():.4f}")

    # 欠損があるので、そのままでは整数型にできない
    try:
        reviews["rating"].astype("int64")
        print("astype('int64') が成功しました（想定外です）")
    except ValueError:
        print("astype('int64')   : ValueError（欠損があるため整数にできない）")

    # 欠損を保ったまま整数として扱いたいときは、欠損を許す Int64 型を使う
    nullable = reviews["rating"].astype("Int64")
    print(f"astype('Int64')   : {nullable.dtype} / 欠損 {int(nullable.isna().sum())} 件")


if __name__ == "__main__":
    main()
