"""セッション 7 の本文・練習問題・解答で共通して使う読み込みと基準日。

同じディレクトリのスクリプトから次のように使います。

    from common import REFERENCE_DATE, load_valid_orders

    valid = load_valid_orders()
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# 「今日」をコードの中で固定する。データ生成時と同じ基準日を使う（本章 8 節で理由を説明）
REFERENCE_DATE = pd.Timestamp("2026-09-01")

# 曜日番号（月曜 = 0）を日本語に直すための対応表
WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]


def load_orders() -> pd.DataFrame:
    """注文データを、ID を文字列・日時を datetime として読み込む（セッション 3 の書き方）。"""
    return pd.read_csv(
        DATA_DIR / "orders.csv",
        dtype={"order_id": "str", "customer_id": "str", "book_id": "str"},
        parse_dates=["ordered_at"],
    )


def load_valid_orders() -> pd.DataFrame:
    """有効注文（重複行とキャンセルを除いた 57,869 件）に売上額 amount を足して返す。"""
    orders = load_orders().drop_duplicates()
    valid = orders.loc[orders["is_canceled"] == 0].copy()
    # 売上は「行ごとに丸めない」。合計してから整数にする（セッション 6 の売上規約）
    valid["amount"] = valid["unit_price"] * valid["quantity"] * (1 - valid["discount_rate"])
    return valid


def make_toy() -> pd.DataFrame:
    """本文の説明で使う 6 件だけの練習用データ（手計算で答え合わせできる大きさ）。"""
    return pd.DataFrame(
        {
            "ordered_at": pd.to_datetime(
                [
                    "2026-08-24 09:12:00",
                    "2026-08-24 20:30:00",
                    "2026-08-25 11:05:00",
                    "2026-08-27 08:45:00",
                    "2026-08-30 22:10:00",
                    "2026-08-31 07:00:00",
                ]
            ),
            "amount": [1000, 2000, 1500, 3000, 2500, 4000],
        }
    )
