"""セッション 25 の本文・練習問題・解答で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import build_pipeline, load_review_table, split

    df = load_review_table()
    X, y = features_target(df)
    X_train, X_test, y_train, y_test = split(X, y)
    model = build_pipeline().fit(X_train, y_train)

この章のモデルは**ロジスティック回帰で固定**します。Pipeline の組み立て方そのものが
主題なので、モデルを差し替えると論点がぼやけるからです。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# 分割と学習の条件は全章で共通（本書の規約）
TEST_SIZE = 0.25
RANDOM_STATE = 42
N_SPLITS = 5
MAX_ITER = 1000
SCORING = "roc_auc"  # 交差検証で使う指標の名前（scikit-learn の決まった文字列）

# 数値 4 列は前章までと同じ。カテゴリは category に region・channel を足して 3 列にする
NUMERIC = ["unit_price", "pages", "published_year", "body_length"]
CATEGORICAL = ["category", "region", "channel"]
FEATURES = NUMERIC + CATEGORICAL

# セッション17 以降で使ってきた構成（カテゴリは category だけ）。比較用に残す
CATEGORICAL_S17 = ["category"]

# ID は数値に見えても文字列として読む（先頭の 0 が落ちないようにする）
ID_COLUMNS = {"review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str"}


def load_review_table() -> pd.DataFrame:
    """高評価レビューの分類に使う表を作る（前章と同じ作り方・同じ行の並び）。

    星の欠損 298 件を落とした 14,169 行に、書籍マスタ・注文の単価・顧客の
    region と channel を結合して返します。**行を並べ替えません。**
    sort_values を挟むと同じ random_state でも別の分割になります。
    """
    reviews = pd.read_csv(DATA_DIR / "reviews.csv", dtype=ID_COLUMNS)
    books = pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"})
    orders = pd.read_csv(
        DATA_DIR / "orders.csv",
        dtype={"order_id": "str"},
        usecols=["order_id", "unit_price"],
    )
    customers = pd.read_csv(
        DATA_DIR / "customers.csv",
        dtype={"customer_id": "str"},
        usecols=["customer_id", "region", "channel"],
    )
    df = (
        reviews.dropna(subset=["rating"])  # 星の欠損を落とす（セッション11）
        .merge(books, on="book_id", how="left")
        .merge(orders.drop_duplicates("order_id"), on="order_id", how="left")
        .merge(customers, on="customer_id", how="left")  # ここで region の欠損が入ってくる
    )
    df["is_high"] = (df["rating"] >= 4).astype("int64")  # 星 4 以上を高評価とする
    return df


def numeric_steps() -> Pipeline:
    """数値列に当てる前処理（欠損を中央値で埋めて標準化する）。strategy は必ず明示する。"""
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]
    )


def categorical_steps() -> Pipeline:
    """カテゴリ列に当てる前処理（欠損を最頻値で埋めて 0/1 に開く）。

    handle_unknown・sparse_output はバージョンで既定値が変わるので必ず書きます。
    """
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )


def build_preprocess(
    numeric: list[str] | None = None, categorical: list[str] | None = None
) -> ColumnTransformer:
    """列の種類ごとに違う前処理を割り当てる。ここに書いた列以外は捨てられる（remainder="drop"）。"""
    numeric = NUMERIC if numeric is None else numeric
    categorical = CATEGORICAL if categorical is None else categorical
    return ColumnTransformer(
        [
            ("num", numeric_steps(), numeric),
            ("cat", categorical_steps(), categorical),
        ]
    )


def build_pipeline(numeric: list[str] | None = None, categorical: list[str] | None = None) -> Pipeline:
    """前処理とモデルを 1 つのオブジェクトにまとめる（この章の最終形）。"""
    return Pipeline(
        [
            ("pre", build_preprocess(numeric, categorical)),
            ("model", LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)),
        ]
    )


def features_target(
    df: pd.DataFrame, numeric: list[str] | None = None, categorical: list[str] | None = None
) -> tuple[pd.DataFrame, pd.Series]:
    """特徴量 X と目的変数 y を切り出す（まだ変換しない・まだ分割しない）。"""
    numeric = NUMERIC if numeric is None else numeric
    categorical = CATEGORICAL if categorical is None else categorical
    return df[numeric + categorical], df["is_high"]


def split(X, y):
    """分割の条件は全章で共通。X の列が何であっても同じ行が評価データになる。"""
    return train_test_split(X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)


def auc_of(model, X_test, y_test) -> float:
    """学習済みモデルの評価データに対する ROC AUC。"""
    return float(roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]))


def holdout_auc(
    df: pd.DataFrame, numeric: list[str] | None = None, categorical: list[str] | None = None
) -> float:
    """1 回だけ分割して測る ROC AUC（Pipeline に載せた正しい手順）。"""
    X, y = features_target(df, numeric, categorical)
    X_train, X_test, y_train, y_test = split(X, y)
    model = build_pipeline(numeric, categorical).fit(X_train, y_train)
    return auc_of(model, X_test, y_test)


def stratified_cv() -> StratifiedKFold:
    """層化 5 分割。fold ごとの正例率を全体にそろえる（セッション22）。"""
    return StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)


def cv_auc(estimator, X, y) -> np.ndarray:
    """交差検証で fold ごとの ROC AUC を測る。estimator が Pipeline なら fold ごとに fit し直される。"""
    return cross_val_score(estimator, X, y, cv=stratified_cv(), scoring=SCORING)


def summarize(scores) -> tuple[float, float]:
    """平均と標準偏差（ddof=0。5 つの fold そのもののばらつき）を返す。"""
    array = np.asarray(scores, dtype="float64")
    return float(array.mean()), float(array.std())


def fmt_scores(scores) -> str:
    """fold ごとのスコアを 1 行に並べる。"""
    return " ".join(f"{float(s):.4f}" for s in scores)


def named_frame(values, names, index=None) -> pd.DataFrame:
    """変換後の行列に列名を付けて DataFrame にする（中身を目で確かめたいときに使う）。"""
    return pd.DataFrame(np.asarray(values, dtype="float64"), columns=list(names), index=index)


def save_figure(fig, name: str) -> str:
    """図を outputs/ に保存して相対パスを返す（MPLBACKEND=Agg なので plt.show は使わない）。"""
    import matplotlib.pyplot as plt  # 図を描くスクリプトだけが必要とするので関数の中で読み込む

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return str(path.relative_to(OUT_DIR.parent))
