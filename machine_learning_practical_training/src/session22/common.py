"""セッション 22 の本文・練習問題・解答で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import cv_auc, load_review_table, stratified_cv

    df = load_review_table()
    print(cv_auc(df, stratified_cv()))

この章のモデルは**ロジスティック回帰で固定**します。交差検証は 1 回の実験で
5 回学習するため、重いモデルを使うと待ち時間が長くなるからです。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import (
    GroupKFold,
    KFold,
    StratifiedKFold,
    TimeSeriesSplit,
    cross_val_score,
    train_test_split,
)
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

# 高評価レビューの分類に使う特徴量（src/verify_setup.py の 5 節と同じ）
NUMERIC = ["unit_price", "pages", "published_year", "body_length"]
CATEGORICAL = ["category"]
FEATURES = NUMERIC + CATEGORICAL

# ID は数値に見えても文字列として読む（先頭の 0 が落ちないようにする）
ID_COLUMNS = {"review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str"}


def load_review_table() -> pd.DataFrame:
    """高評価レビューの分類に使う表を作る（src/verify_setup.py の 5 節と同じ作り方・同じ並び）。

    星の欠損 298 件を落とした 14,169 行に、書籍マスタと注文の単価を結合して返します。
    **行を並べ替えません。** sort_values を挟むと同じ random_state でも別の分割になります。
    """
    reviews = pd.read_csv(DATA_DIR / "reviews.csv", dtype=ID_COLUMNS, parse_dates=["reviewed_at"])
    books = pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"})
    orders = pd.read_csv(
        DATA_DIR / "orders.csv",
        dtype={"order_id": "str"},
        usecols=["order_id", "unit_price"],
    )
    df = (
        reviews.dropna(subset=["rating"])  # 星の欠損を落とす（セッション11）
        .merge(books, on="book_id", how="left")
        .merge(orders.drop_duplicates("order_id"), on="order_id", how="left")
    )
    df["is_high"] = (df["rating"] >= 4).astype("int64")  # 星 4 以上を高評価とする
    return df


def build_preprocess(numeric: list[str] | None = None, categorical: list[str] | None = None) -> ColumnTransformer:
    """数値列を標準化し、カテゴリ列を 0/1 に開く前処理を作る（引数は常に明示する）。"""
    numeric = NUMERIC if numeric is None else numeric
    categorical = CATEGORICAL if categorical is None else categorical
    transformers: list[tuple] = [("num", StandardScaler(), numeric)]
    if categorical:
        # handle_unknown・sparse_output はバージョンで既定値が変わるので必ず書く
        transformers.append(("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical))
    return ColumnTransformer(transformers)


def build_model(numeric: list[str] | None = None, categorical: list[str] | None = None) -> Pipeline:
    """前処理とロジスティック回帰をひとまとめにしたモデルを作る。

    Pipeline に載せておくと、交差検証の fold ごとに「訓練データだけで fit → 検証データは
    transform だけ」が自動で守られます。Pipeline の組み立て方そのものは
    「セッション25：前処理と学習をひとつにまとめる」で正面から扱います。
    """
    return Pipeline(
        [
            ("pre", build_preprocess(numeric, categorical)),
            ("model", LogisticRegression(max_iter=MAX_ITER)),
        ]
    )


def features_target(
    df: pd.DataFrame, numeric: list[str] | None = None, categorical: list[str] | None = None
) -> tuple[pd.DataFrame, pd.Series]:
    """特徴量 X と目的変数 y を切り出す（まだ分割しない）。"""
    numeric = NUMERIC if numeric is None else numeric
    categorical = CATEGORICAL if categorical is None else categorical
    return df[numeric + categorical], df["is_high"]


def holdout_auc(
    df: pd.DataFrame, numeric: list[str] | None = None, categorical: list[str] | None = None
) -> float:
    """1 回だけ分割して測る ROC AUC（これまでの章と同じ手順）。"""
    X, y = features_target(df, numeric, categorical)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    model = build_model(numeric, categorical).fit(X_train, y_train)
    return float(roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]))


def cv_auc(
    df: pd.DataFrame,
    cv,
    groups: pd.Series | None = None,
    numeric: list[str] | None = None,
    categorical: list[str] | None = None,
) -> np.ndarray:
    """交差検証で fold ごとの ROC AUC を測る（fold の数だけ学習する）。"""
    X, y = features_target(df, numeric, categorical)
    return cross_val_score(build_model(numeric, categorical), X, y, cv=cv, groups=groups, scoring=SCORING)


def fold_positive_rates(
    df: pd.DataFrame,
    cv,
    groups: pd.Series | None = None,
    numeric: list[str] | None = None,
    categorical: list[str] | None = None,
) -> list[float]:
    """fold ごとの「検証データの正例率」を返す。層化の効き方を目で見るために使う。"""
    X, y = features_target(df, numeric, categorical)
    return [float(y.iloc[test].mean()) for _, test in cv.split(X, y, groups)]


def stratified_cv() -> StratifiedKFold:
    """層化 K 分割。fold ごとの正例率を全体にそろえる。"""
    return StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)


def plain_cv() -> KFold:
    """層化しない K 分割。正例率はそろわない。"""
    return KFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)


def group_cv() -> GroupKFold:
    """グループ分割。同じグループ（顧客）が訓練と検証に分かれないようにする。"""
    return GroupKFold(n_splits=N_SPLITS)


def series_cv() -> TimeSeriesSplit:
    """時系列分割。過去で学習して未来で検証する（並び順に意味がある）。"""
    return TimeSeriesSplit(n_splits=N_SPLITS)


def fmt_scores(scores) -> str:
    """fold ごとのスコアを 1 行に並べる。"""
    return " ".join(f"{float(s):.4f}" for s in scores)


def summarize(scores) -> tuple[float, float]:
    """平均と標準偏差（ddof=0。5 つの fold そのもののばらつき）を返す。"""
    array = np.asarray(scores, dtype="float64")
    return float(array.mean()), float(array.std())


def save_figure(fig, name: str) -> Path:
    """図を outputs/ に保存してパスを返す（MPLBACKEND=Agg なので plt.show は使わない）。"""
    import matplotlib.pyplot as plt  # 図を描くスクリプトだけが必要とするので関数の中で読み込む

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
