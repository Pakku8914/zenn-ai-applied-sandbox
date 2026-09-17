"""セッション 17 の本文・練習問題・解答で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import fit_model, load_review_table, prepare, split_xy

    df = load_review_table()
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    model = fit_model(train, y_train)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# データ分割の条件は全章で共通（本書の規約）
TEST_SIZE = 0.25
RANDOM_STATE = 42
# 既定の max_iter=100 では収束しないことがある（セッション12 で見た ConvergenceWarning）
MAX_ITER = 1000
# 木モデルと比べるときの本数（セッション18・19 と同じ条件にそろえる）
N_ESTIMATORS = 200

# 高評価レビューの分類に使う特徴量（src/verify_setup.py の 5 節と同じ）
NUMERIC = ["unit_price", "pages", "published_year", "body_length"]
CATEGORICAL = ["category"]
FEATURES = NUMERIC + CATEGORICAL

# 確率をクラスに変えるときの境目。0.5 は「既定値」であって「正解」ではない
DEFAULT_THRESHOLD = 0.5
# 本文と練習問題で様子を見る閾値（0.5 の前後を並べる）
THRESHOLDS = [0.3, 0.5, 0.7, 0.8, 0.9]


def load_review_table() -> pd.DataFrame:
    """高評価レビューの分類に使う表を作る（src/verify_setup.py の 5 節と同じ作り方・同じ並び）。

    星が欠損している 298 件を落とし、書籍マスタと注文の単価を結合して 14,169 行にします。
    **並べ替えません。** sort_values を挟むと同じ random_state でも別の分割になります（本書の規約）。
    """
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
    df["is_high"] = (df["rating"] >= 4).astype("int64")  # 星 4 以上を「高評価」とする
    return df


def split_xy(df: pd.DataFrame):
    """特徴量と目的変数を切り出して訓練・評価に分ける（条件は全章共通）。"""
    X = df[FEATURES]
    y = df["is_high"]
    return train_test_split(X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)


def make_preprocess() -> ColumnTransformer:
    """数値 4 列を標準化し、category を 0/1 の 5 列に開く（引数は常に明示する）。"""
    return ColumnTransformer(
        [
            ("num", StandardScaler(), NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
        ]
    )


def clean_names(pre: ColumnTransformer) -> list[str]:
    """ColumnTransformer が付ける接頭辞（num__ / cat__）を落として読みやすくする。"""
    return [name.split("__")[-1] for name in pre.get_feature_names_out()]


def prepare(X_train: pd.DataFrame, X_test: pd.DataFrame):
    """前処理を訓練データだけで fit し、両方を transform して列名も返す。

    返り値は (前処理器, 訓練データの行列, 評価データの行列, 列名のリスト) です。
    """
    pre = make_preprocess()
    train = pre.fit_transform(X_train)  # fit は訓練データだけ（セッション12）
    test = pre.transform(X_test)  # 評価データは transform だけ
    return pre, train, test, clean_names(pre)


def fit_model(X_train_t, y_train, max_iter: int = MAX_ITER) -> LogisticRegression:
    """ロジスティック回帰を学習する。

    既定の solver（lbfgs）では random_state は使われませんが、本書の習慣として必ず明示します。
    既定では L2 正則化（C=1.0）が掛かっている点にも注意してください（セッション16 の Ridge と同じ考え方）。
    """
    model = LogisticRegression(max_iter=max_iter, random_state=RANDOM_STATE)
    model.fit(X_train_t, y_train)
    return model


def sigmoid(z):
    """シグモイド関数。対数オッズ z（−∞〜+∞）を確率（0〜1）に変える。"""
    return 1.0 / (1.0 + np.exp(-z))


def basic_scores(y_true, proba_matrix) -> dict[str, float]:
    """accuracy・ROC AUC・対数損失をまとめて返す（accuracy は閾値 0.5 での結果）。"""
    proba = proba_matrix[:, 1]
    return {
        "accuracy": float(accuracy_score(y_true, (proba >= DEFAULT_THRESHOLD).astype("int64"))),
        "roc_auc": float(roc_auc_score(y_true, proba)),
        # 対数損失は predict_proba の 2 列をそのまま渡す（列の順番は model.classes_ と同じ）
        "log_loss": float(log_loss(y_true, proba_matrix)),
    }


def baseline_scores(y_true) -> dict[str, float]:
    """「全部 1（高評価）」と予測するだけのベースライン。何も学習していない水準の目安。"""
    always_one = np.ones(len(y_true), dtype="int64")
    constant_score = np.full(len(y_true), 0.5)  # 全員同じ点数なので順位が付かない
    return {
        "accuracy": float(accuracy_score(y_true, always_one)),
        "roc_auc": float(roc_auc_score(y_true, constant_score)),
    }


def coefficient_table(model: LogisticRegression, names: list[str]) -> pd.DataFrame:
    """係数とオッズ比（= exp(係数)）を並べた表を係数の大きい順に作る。"""
    table = pd.DataFrame({"feature": names, "coef": model.coef_[0]})
    table["odds_ratio"] = np.exp(table["coef"])
    return table.sort_values("coef", ascending=False).reset_index(drop=True)


def print_coefficient_table(table: pd.DataFrame) -> None:
    """係数の表を 1 行 1 列で表示する。"""
    for row in table.itertuples(index=False):
        print(f"{row.feature:<22} 係数 {row.coef:+.4f} / オッズ比 {row.odds_ratio:.4f}")


def numeric_scale(pre: ColumnTransformer, column: str) -> float:
    """標準化に使った 1 標準偏差（元の単位）を取り出す。自分で std() を計算し直さない。

    スケーラが fit したのは訓練データで、しかも母標準偏差（ddof=0）です。
    全データに pandas の std()（既定は ddof=1）を当てると別の値になります。
    """
    return float(pre.named_transformers_["num"].scale_[NUMERIC.index(column)])


def odds_multiplier(coef: float, delta: float, scale: float) -> float:
    """元の単位で delta だけ増えたときのオッズの倍率を返す（標準化した係数から逆算する）。"""
    return float(np.exp(coef * delta / scale))


def threshold_metrics(y_true, proba, threshold: float) -> dict[str, float]:
    """閾値を 1 つ決めて、陽性と予測した件数・適合率・再現率・F1・accuracy を返す。"""
    y_pred = (proba >= threshold).astype("int64")
    return {
        "threshold": float(threshold),
        "n_positive": int(y_pred.sum()),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
    }


def threshold_table(y_true, proba, thresholds=None) -> pd.DataFrame:
    """複数の閾値について threshold_metrics を並べた表を作る。"""
    targets = THRESHOLDS if thresholds is None else thresholds
    return pd.DataFrame([threshold_metrics(y_true, proba, t) for t in targets])


def print_threshold_table(table: pd.DataFrame) -> None:
    """閾値の表を 1 行 1 閾値で表示する。"""
    print("閾値 | 適合率 | 再現率 |   F1   | 陽性と予測 | accuracy")
    for row in table.itertuples(index=False):
        print(
            f"{row.threshold:.1f}  | {row.precision:.4f} | {row.recall:.4f} | {row.f1:.4f} |"
            f" {row.n_positive:>6,} 件 | {row.accuracy:.4f}"
        )
