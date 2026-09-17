"""セッション 4 の練習問題・解答で共通して使うデータ読み込み。

同じディレクトリのスクリプトから次のように使います。

    from common import load_orders

    orders = load_orders()
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def load_orders() -> pd.DataFrame:
    """注文データを、ID を文字列・日時を datetime として読み込む（セッション 3 の書き方）。"""
    return pd.read_csv(
        DATA_DIR / "orders.csv",
        dtype={"order_id": "str", "customer_id": "str", "book_id": "str"},
        parse_dates=["ordered_at"],
    )
