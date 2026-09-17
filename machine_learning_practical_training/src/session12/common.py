"""セッション 12 の本文・練習問題・解答で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import load_orders, outlier_mask

    quantity = load_orders()["quantity"]
    mask = outlier_mask(quantity, "sigma")
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.preprocessing import MinMaxScaler, StandardScaler

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# まとめ買いの境目。ふつうの注文は 1〜3 冊しかないので、15 冊以上は別の買い方だと見なす
BULK_THRESHOLD = 15
# 上限打ち切り（クリッピング）の上限。「ふつうの注文」の最大値である 3 冊にそろえる
CLIP_UPPER = 3

# 高評価レビューの分類に使う特徴量（src/verify_setup.py の 5 節と同じ）
NUMERIC_FEATURES = ["unit_price", "pages", "published_year", "body_length"]
CATEGORY_FEATURE = "category"
# category を 0/1 の列に開いたときの列名。モデルに渡す列名は英数字にそろえておくと、
# ライブラリ側の制約（列名に使えない文字がある）に引っかからない
CATEGORY_COLUMNS = {
    "ビジネス": "cat_business",
    "児童書": "cat_kids",
    "実用書": "cat_practical",
    "小説": "cat_novel",
    "技術書": "cat_tech",
}

# データ分割の条件は全章で共通（本書の規約）
TEST_SIZE = 0.25
RANDOM_STATE = 42


def load_orders() -> pd.DataFrame:
    """注文データを読み込み、完全重複 30 件を落として 60,031 行で返す（セッション4の習慣）。"""
    orders = pd.read_csv(
        DATA_DIR / "orders.csv",
        dtype={"order_id": "str", "customer_id": "str", "book_id": "str"},
        parse_dates=["ordered_at"],
    )
    return orders.drop_duplicates()


def add_amount(orders: pd.DataFrame) -> pd.DataFrame:
    """キャンセルを除いた有効注文に売上額 amount を足して返す（行ごとには丸めない）。"""
    valid = orders.loc[orders["is_canceled"] == 0].copy()
    valid["amount"] = valid["unit_price"] * valid["quantity"] * (1 - valid["discount_rate"])
    return valid


def yen(value: float) -> str:
    """金額を表示用の文字列にする。合計してから round で整数にする（切り捨てない）。"""
    return f"{round(float(value)):,}"


def outlier_bounds(values: pd.Series, method: str) -> tuple[float, float]:
    """外れ値と見なす下限・上限を返す。method は "iqr"（四分位範囲）か "sigma"（標準偏差）。"""
    if method == "iqr":
        q1, q3 = values.quantile(0.25), values.quantile(0.75)
        iqr = q3 - q1
        return float(q1 - 1.5 * iqr), float(q3 + 1.5 * iqr)
    if method == "sigma":
        mean, sd = values.mean(), values.std()  # std() の ddof は既定で 1（標本標準偏差）
        return float(mean - 3 * sd), float(mean + 3 * sd)
    raise ValueError(f"method は 'iqr' か 'sigma' のどちらかです: {method!r}")


def outlier_mask(values: pd.Series, method: str) -> pd.Series:
    """外れ値の行が True になる真偽値の Series を返す。"""
    lower, upper = outlier_bounds(values, method)
    return (values < lower) | (values > upper)


def load_review_features() -> pd.DataFrame:
    """高評価レビューの分類に使う表を作る（src/verify_setup.py と同じ作り方・同じ行の並び）。"""
    books = pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"})
    reviews = pd.read_csv(
        DATA_DIR / "reviews.csv",
        dtype={"review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str"},
    )
    orders = pd.read_csv(
        DATA_DIR / "orders.csv",
        dtype={"order_id": "str"},
        usecols=["order_id", "unit_price"],
    )
    df = (
        reviews.dropna(subset=["rating"])  # 星の欠損 298 件を落とす（セッション11）
        .merge(books, on="book_id", how="left")
        .merge(orders.drop_duplicates("order_id"), on="order_id", how="left")
    )
    df["is_high"] = (df["rating"] >= 4).astype(int)
    # 並べ替えない。sort_values を挟むと同じ random_state でも別の分割になる（本書の規約）
    return df


def make_design_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """数値 4 列と、category を 0/1 に開いた 5 列を横に並べた 9 列の特徴量を作る。

    カテゴリの数値化は「セッション13：カテゴリ変数のエンコーディング」で正面から扱います。
    ここでは 5 つの 0/1 列に開くだけ、と理解しておいてください。
    """
    dummies = pd.get_dummies(df[CATEGORY_FEATURE], dtype="float64")  # 列は名前順に並ぶ
    dummies = dummies.rename(columns=CATEGORY_COLUMNS)  # 並びは変えず、名前だけ英数字にする
    return pd.concat([df[NUMERIC_FEATURES].astype("float64"), dummies], axis=1)


def scale_numeric(
    X_train: pd.DataFrame, X_test: pd.DataFrame, scaler_name: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """数値 4 列だけをスケーリングする。fit は訓練データだけ、検証データは transform だけ。"""
    if scaler_name == "none":
        return X_train.copy(), X_test.copy()
    scaler = {"standard": StandardScaler(), "minmax": MinMaxScaler()}[scaler_name]
    train, test = X_train.copy(), X_test.copy()
    train[NUMERIC_FEATURES] = scaler.fit_transform(X_train[NUMERIC_FEATURES])
    test[NUMERIC_FEATURES] = scaler.transform(X_test[NUMERIC_FEATURES])  # fit しない
    return train, test
