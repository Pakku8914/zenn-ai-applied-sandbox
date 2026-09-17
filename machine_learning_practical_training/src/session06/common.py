"""セッション 6 で共通して使うデータ読み込みと「有効注文」の作り方。

    from common import load_tables, valid_orders

    books, customers, orders = load_tables()
    valid = valid_orders(orders)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def load_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """books / customers / orders を、ID を文字列・日時を datetime として読み込む。"""
    books = pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"})
    customers = pd.read_csv(
        DATA_DIR / "customers.csv",
        dtype={"customer_id": "str"},
        parse_dates=["signup_date"],
    )
    orders = pd.read_csv(
        DATA_DIR / "orders.csv",
        dtype={"order_id": "str", "customer_id": "str", "book_id": "str"},
        parse_dates=["ordered_at"],
    )
    return books, customers, orders


def valid_orders(orders: pd.DataFrame) -> pd.DataFrame:
    """重複行とキャンセル注文を除いた「有効注文」に、金額の列 revenue を足して返す。

    revenue は行ごとに丸めない（本書の規約）。丸めるのは表示するときだけ。
    """
    unique_orders = orders.drop_duplicates()
    valid = unique_orders.loc[unique_orders["is_canceled"] == 0].copy()
    valid["revenue"] = valid["unit_price"] * valid["quantity"] * (1 - valid["discount_rate"])
    return valid
