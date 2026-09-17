"""型を明示して CSV を読み込み、pandas 3.0 の既定の型を確認する。

使い方:
    docker compose exec lab python src/session03/read_typed.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# 読み込みの設定は「辞書」で 1 か所にまとめておく（章をまたいで再利用できる）
BOOKS_DTYPE = {
    "book_id": "str",
    "category": "str",
    "price": "int64",
    "pages": "int64",
    "published_year": "int64",
}
# parse_dates で日時にする列は dtype には書かない（役割が重なるため）
CUSTOMERS_DTYPE = {
    "customer_id": "str",
    "birth_year": "int64",
    "region": "str",
    "channel": "str",
}


def main() -> None:
    books = pd.read_csv(DATA_DIR / "books.csv", dtype=BOOKS_DTYPE)
    print("■ books の dtype（明示した型で読めているか）")
    print(books.dtypes)

    customers = pd.read_csv(
        DATA_DIR / "customers.csv",
        dtype=CUSTOMERS_DTYPE,
        parse_dates=["signup_date"],
    )
    print("\n■ customers の dtype")
    print(customers.dtypes)
    print(f"\nregion の欠損 : {int(customers['region'].isna().sum())} 件 / {len(customers)} 行")

    # parse_dates を指定しないと、日時は「文字列」として読まれる
    orders_raw = pd.read_csv(DATA_DIR / "orders.csv")
    orders = pd.read_csv(DATA_DIR / "orders.csv", parse_dates=["ordered_at"])
    print("\n■ 日時列は指定しないと文字列になる")
    print(f"ordered_at（parse_dates なし）: {orders_raw['ordered_at'].dtype}")
    print(f"ordered_at（parse_dates あり）: {orders['ordered_at'].dtype}")
    print(f"日時として扱えているか        : {orders['ordered_at'].dt.year.between(2024, 2026).all()}")

    # 文字列は 1 件ごとに Python の文字列オブジェクトを持つので、意外に重い
    mb = orders.memory_usage(deep=True).sum() / 1024**2
    print(f"\norders のメモリ使用量（deep=True）: {mb:.2f} MB")


if __name__ == "__main__":
    main()
