"""セッション 8 の本文・練習問題・解答で共通して使う読み込みと図の保存。

同じディレクトリのスクリプトから次のように使います。

    from common import load_reviews, save_fig

    reviews = load_reviews()
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 画面のないコンテナ内で図を PNG として保存するための設定
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# カテゴリは「平均価格の安い順」に固定する。図ごとに並びが変わると読み比べられない
CATEGORY_ORDER = ["小説", "児童書", "実用書", "ビジネス", "技術書"]

# 年代の区切り。人数の少ない両端（10 代以下・70 代以上）はまとめる
AGE_BINS = [0, 29, 39, 49, 59, 200]
AGE_LABELS = ["20代以下", "30代", "40代", "50代", "60代以上"]


def load_books() -> pd.DataFrame:
    """書籍マスタ（600 行）。"""
    return pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"})


def load_customers() -> pd.DataFrame:
    """顧客マスタ（8,000 行）。今章で使うのは birth_year だけ。"""
    return pd.read_csv(DATA_DIR / "customers.csv", dtype={"customer_id": "str"})


def load_orders() -> pd.DataFrame:
    """注文データ（完全重複 30 件を落とした 60,031 行。セッション 4 の習慣どおり）。"""
    ids = {"order_id": "str", "customer_id": "str", "book_id": "str"}
    orders = pd.read_csv(DATA_DIR / "orders.csv", dtype=ids, parse_dates=["ordered_at"])
    return orders.drop_duplicates()  # 60,061 行 → 60,031 行


def load_reviews() -> pd.DataFrame:
    """レビュー（14,467 行。星は 298 件が未入力）。"""
    ids = {"review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str"}
    return pd.read_csv(DATA_DIR / "reviews.csv", dtype=ids, parse_dates=["reviewed_at"])


def load_valid_orders() -> pd.DataFrame:
    """有効注文（重複行とキャンセルを除いた 57,869 件）に売上額 amount を足して返す。"""
    orders = load_orders()  # 重複はここで既に落ちている
    valid = orders.loc[orders["is_canceled"] == 0].copy()
    # 売上は行ごとに丸めない。合計してから整数にする（セッション 6 の売上規約）
    valid["amount"] = valid["unit_price"] * valid["quantity"] * (1 - valid["discount_rate"])
    return valid


def load_rated_reviews() -> pd.DataFrame:
    """星が入っているレビュー（14,169 件）に書籍マスタを結合して返す。"""
    return load_reviews().dropna(subset=["rating"]).merge(load_books(), on="book_id", how="left")


def monthly_amount() -> pd.Series:
    """有効注文の売上を月次（月末ラベル）に集計した Series を返す（セッション 7 の復習）。"""
    valid = load_valid_orders()
    return valid.set_index("ordered_at")["amount"].sort_index().resample("ME").sum()


def save_fig(fig: Figure, name: str) -> None:
    """図を outputs/ に保存し、保存先を表示してから Figure を閉じる。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_DIR / name, dpi=110, bbox_inches="tight")
    plt.close(fig)  # 閉じないと Figure が開いたまま溜まっていく
    print(f"図を保存しました: outputs/{name}")
