"""セッション 9 の本文・練習問題・解答で共通して使う読み込みと小さな題材。

同じディレクトリのスクリプトから次のように使います。

    from common import load_orders, load_rated_reviews

    reviews = load_rated_reviews()
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# 図や表で使う列の日本語ラベル（図のラベルは日本語で書く、という本書の方針）
LABEL_JA = {
    "rating": "星",
    "body_length": "本文の長さ",
    "price": "価格",
    "pages": "ページ数",
    "published_year": "刊行年",
}

# 価格を 4 等分したときの呼び名。表示幅をそろえるため、どれも 4 文字にしてある
PRICE_BANDS = ["最も安い", "やや安い", "やや高い", "最も高い"]


def pad_ja(text: str, width: int) -> str:
    """全角を 2 文字分と数えて右側に空白を足す（出力の桁をそろえるためだけの関数）。"""
    display = sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)
    return text + " " * max(width - display, 0)


def load_orders(dedupe: bool = True) -> pd.DataFrame:
    """注文データを読み込む。既定では完全重複 30 件を落とす（60,031 行・セッション 4 の習慣）。"""
    orders = pd.read_csv(
        DATA_DIR / "orders.csv",
        dtype={"order_id": "str", "customer_id": "str", "book_id": "str"},
        parse_dates=["ordered_at"],
    )
    return orders.drop_duplicates() if dedupe else orders  # dedupe=False なら生の 60,061 行


def load_valid_orders() -> pd.DataFrame:
    """有効注文（重複行とキャンセルを除いた 57,869 件）に売上額 amount を足して返す。"""
    orders = load_orders()  # 重複 30 件はここで落ちている
    valid = orders.loc[orders["is_canceled"] == 0].copy()
    # 売上は行ごとに丸めない。合計してから整数にする（セッション 6 の売上規約）
    valid["amount"] = valid["unit_price"] * valid["quantity"] * (1 - valid["discount_rate"])
    return valid


def load_rated_reviews() -> pd.DataFrame:
    """星が入っているレビュー 14,169 件に、書籍の情報を結合して返す。"""
    books = pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"})
    reviews = pd.read_csv(
        DATA_DIR / "reviews.csv",
        dtype={"review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str"},
        parse_dates=["reviewed_at"],
    )
    rated = reviews.dropna(subset=["rating"])  # 星の欠損 298 件を落とす
    return rated.merge(books, on="book_id", how="left")


def make_toy_curves() -> pd.DataFrame:
    """x と 3 通りの y（直線・放物線・単調な曲線）。手計算で確かめられる 7 点だけ。"""
    x = list(range(-3, 4))
    return pd.DataFrame(
        {
            "x": x,
            "line": [2 * v + 1 for v in x],  # 直線
            "parabola": [v**2 for v in x],  # 放物線（左右対称）
            "cubic": [v**3 for v in x],  # 単調に増えるが直線ではない
        }
    )
