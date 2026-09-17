"""セッション 13 の本文・練習問題・解答で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import load_review_features, split_features

    X_train, X_test, y_train, y_test = split_features(load_review_features())
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# 高評価レビューの分類に使う特徴量（src/verify_setup.py の 5 節・前章と同じ）
NUMERIC_FEATURES = ["unit_price", "pages", "published_year", "body_length"]
CATEGORY_FEATURE = "category"
ID_FEATURE = "book_id"
# region の欠損 392 件を埋める文字列。「未入力」であることを列名に残すため定数にする
MISSING_LABEL = "不明"

# データ分割の条件は全章で共通（本書の規約）
TEST_SIZE = 0.25
RANDOM_STATE = 42


def load_customers() -> pd.DataFrame:
    """顧客マスタ 8,000 行。region には欠損 392 件がそのまま残っている。"""
    return pd.read_csv(
        DATA_DIR / "customers.csv",
        dtype={"customer_id": "str"},
        parse_dates=["signup_date"],
    )


def load_books() -> pd.DataFrame:
    """書籍マスタ 600 行。category（5 水準）と book_id（600 水準）を使う。"""
    return pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"})


def load_review_features() -> pd.DataFrame:
    """高評価レビューの分類に使う表を作る（前章と同じ作り方・同じ行の並び）。"""
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
        .merge(load_books(), on="book_id", how="left")
        .merge(orders.drop_duplicates("order_id"), on="order_id", how="left")
    )
    df["is_high"] = (df["rating"] >= 4).astype(int)
    # 並べ替えない。sort_values を挟むと同じ random_state でも別の分割になる（本書の規約）
    return df


def split_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """前章と同じ条件で訓練・評価に分ける。カテゴリ列は変換せずそのまま持ち回る。"""
    X = df[NUMERIC_FEATURES + [CATEGORY_FEATURE, ID_FEATURE]]
    y = df["is_high"]
    return train_test_split(X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)


def scaled_numeric(X_train: pd.DataFrame, X_test: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """数値 4 列を標準化する。fit は訓練データだけ、評価データは transform だけ（前章）。"""
    scaler = StandardScaler().set_output(transform="pandas").fit(X_train[NUMERIC_FEATURES])
    return scaler.transform(X_train[NUMERIC_FEATURES]), scaler.transform(X_test[NUMERIC_FEATURES])


def onehot_features(
    X_train: pd.DataFrame, X_test: pd.DataFrame, column: str = CATEGORY_FEATURE
) -> tuple[pd.DataFrame, pd.DataFrame, OneHotEncoder]:
    """列を水準ごとの 0/1 の列に開く。未知の水準はすべて 0 のベクトルにする。

    sparse_output と handle_unknown は必ず明示する（版によって既定値が変わるため）。
    """
    encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    encoder.set_output(transform="pandas").fit(X_train[[column]])
    return encoder.transform(X_train[[column]]), encoder.transform(X_test[[column]]), encoder


def ordinal_features(
    X_train: pd.DataFrame, X_test: pd.DataFrame, column: str = CATEGORY_FEATURE
) -> tuple[pd.DataFrame, pd.DataFrame, OrdinalEncoder]:
    """列を 1 本の番号の列にする（Label エンコーディング）。未知の水準は -1 にする。"""
    encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
    encoder.set_output(transform="pandas").fit(X_train[[column]])
    rename = {column: f"{column}_code"}  # 中身が番号であることを列名に残す
    train = encoder.transform(X_train[[column]]).rename(columns=rename)
    test = encoder.transform(X_test[[column]]).rename(columns=rename)
    return train, test, encoder


def target_means(keys: pd.Series, y: pd.Series) -> pd.Series:
    """水準ごとの目的変数の平均（ターゲットエンコーディングの対応表）を返す。"""
    return y.groupby(keys).mean()


def target_features(
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    means: pd.Series,
    prior: float,
    column: str = CATEGORY_FEATURE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """対応表を当てて 1 本の列にする。表に無い水準は prior（全体の平均）で埋める。"""
    name = f"{column}_target"

    def apply(frame: pd.DataFrame) -> pd.DataFrame:
        values = frame[column].map(means).fillna(prior).astype("float64")
        return pd.DataFrame({name: values}, index=frame.index)

    return apply(X_train), apply(X_test)


def design(numeric: pd.DataFrame, encoded: pd.DataFrame) -> pd.DataFrame:
    """標準化した数値の列と、変換したカテゴリの列を横に並べて特徴量にする。"""
    return pd.concat([numeric, encoded], axis=1)


def auc_of(model, X_train: pd.DataFrame, y_train, X_test: pd.DataFrame, y_test) -> float:
    """モデルを学習し、評価データの ROC AUC を返す。

    列名ではなく値だけを渡す（`to_numpy()`）。列名に日本語が入っていても動くようにするためで、
    渡す数値は DataFrame のときと同じです。
    """
    model.fit(X_train.to_numpy(), y_train)
    return float(roc_auc_score(y_test, model.predict_proba(X_test.to_numpy())[:, 1]))
