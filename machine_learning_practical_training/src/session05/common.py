"""セッション 5 で共通して使うデータ読み込みと、行数の検算ヘルパー。

同じディレクトリのスクリプトから次のように使います。

    from common import load_all, report

    books, customers, orders, reviews = load_all()
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def load_books() -> pd.DataFrame:
    """書籍マスタ。book_id は文字列として読む（ゼロ埋めを壊さないため）。"""
    return pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"})


def load_customers() -> pd.DataFrame:
    """顧客マスタ。"""
    return pd.read_csv(
        DATA_DIR / "customers.csv",
        dtype={"customer_id": "str"},
        parse_dates=["signup_date"],
    )


def load_orders() -> pd.DataFrame:
    """注文明細（重複行 30 件を含む生のまま）。"""
    return pd.read_csv(
        DATA_DIR / "orders.csv",
        dtype={"order_id": "str", "customer_id": "str", "book_id": "str"},
        parse_dates=["ordered_at"],
    )


def load_reviews() -> pd.DataFrame:
    """レビュー。"""
    return pd.read_csv(
        DATA_DIR / "reviews.csv",
        dtype={"review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str"},
        parse_dates=["reviewed_at"],
    )


def load_all() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """4 つのファイルをまとめて読み込む。"""
    return load_books(), load_customers(), load_orders(), load_reviews()


def report(label: str, before: int, after: int) -> None:
    """結合の前後で行数がどう変わったかを 1 行で表示する（検算の習慣）。"""
    diff = after - before
    sign = "±0" if diff == 0 else f"{diff:+,}"
    print(f"{label}: {before:,} 行 → {after:,} 行 ({sign})")
