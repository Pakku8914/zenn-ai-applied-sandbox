"""head・info・describe でデータの全体像を掴む。

describe の count が行数より少ないことから、欠損値の存在に気づく流れを確認する。

使い方:
    docker compose exec lab python src/session03/overview.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def main() -> None:
    books = pd.read_csv(DATA_DIR / "books.csv")
    reviews = pd.read_csv(DATA_DIR / "reviews.csv", parse_dates=["reviewed_at"])

    print("■ head(3) — 先頭だけ見る")
    print(books.head(3))

    print("\n■ info() — 列・件数・型・欠損の有無")
    # メモリ使用量は deep=True で別に測るので、ここでは表示しない
    books.info(memory_usage=False)

    print("\n■ describe() — books の price の分布")
    print(books["price"].describe().round(2))

    print("\n■ describe() — reviews の rating の分布")
    print(reviews["rating"].describe().round(4))

    # count が行数より少ない = 欠損値がある、という読み方
    count = int(reviews["rating"].describe()["count"])
    print(f"\nrating の dtype : {reviews['rating'].dtype}")
    print(f"行数 {len(reviews)} - describe の count {count} = {len(reviews) - count} 件が欠損")
    print(f"isna().sum() で数えても : {int(reviews['rating'].isna().sum())} 件")


if __name__ == "__main__":
    main()
