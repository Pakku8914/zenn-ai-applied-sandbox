"""セッション 19 の本文・練習問題・解答で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import load_review_table, make_lgbm, prepare, split_xy

    df = load_review_table()
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    model = make_lgbm().fit(train, y_train)

このディレクトリのスクリプトは、他のセッションのディレクトリを一切参照しません
（読者がこの章のファイルだけを作って実行できるようにするためです）。
"""

from __future__ import annotations

from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import accuracy_score, log_loss, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# データ分割の条件は全章で共通（本書の規約）
TEST_SIZE = 0.25
RANDOM_STATE = 42

# この章の主役になる 3 つのパラメータ（値は LightGBM の既定値、本数だけ本書の既定）
N_ESTIMATORS = 200  # 木の本数 ＝ ブースティングを何回繰り返すか
LEARNING_RATE = 0.1  # 学習率。1 本ぶんの修正をどれだけ効かせるか（LightGBM の既定値）
NUM_LEAVES = 31  # 1 本の木が持てる葉の数の上限（LightGBM の既定値）

SLOW_LEARNING_RATE = 0.05  # 本文でもう 1 段階ゆっくり学習させるときの値
MANY_ESTIMATORS = 1000  # 早期終了に止め時を任せるときの上限
EARLY_STOPPING_ROUNDS = 50  # 何回続けて改善しなかったら止めるか
DEFAULT_THRESHOLD = 0.5  # 確率をクラスに変える境目（既定値であって正解ではない）

# 高評価レビューの分類に使う特徴量（src/verify_setup.py の 5 節と同じ）
NUMERIC = ["unit_price", "pages", "published_year", "body_length"]
CATEGORICAL = ["category"]
FEATURES = NUMERIC + CATEGORICAL


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


def native_frames(X_train: pd.DataFrame, X_test: pd.DataFrame):
    """category 列を pandas の category 型にしたまま渡すための表を作る。

    水準（カテゴリの一覧と並び）は訓練データから決め、評価データにも同じものを適用します。
    別々に astype すると水準の並びがずれ、同じ文字列が別の番号になってしまいます。
    """
    dtype = pd.CategoricalDtype(categories=sorted(X_train["category"].unique()), ordered=False)
    return (
        X_train.assign(category=X_train["category"].astype(dtype)),
        X_test.assign(category=X_test["category"].astype(dtype)),
    )


def make_lgbm(**overrides) -> lgb.LGBMClassifier:
    """本書の既定条件で LightGBM の分類器を作る。変えたいパラメータだけ引数で上書きする。

    random_state と verbose=-1 は必ず指定します（前者は再現性のため、
    後者は学習中のログで出力が埋まるのを防ぐためです）。
    """
    params = {
        "n_estimators": N_ESTIMATORS,
        "learning_rate": LEARNING_RATE,
        "num_leaves": NUM_LEAVES,
        "random_state": RANDOM_STATE,
        "verbose": -1,
    }
    params.update(overrides)
    return lgb.LGBMClassifier(**params)


def scores_from_proba(y_true, proba) -> dict[str, float]:
    """予測確率から accuracy（閾値 0.5）と ROC AUC を求める。"""
    proba = np.asarray(proba, dtype="float64")
    return {
        "accuracy": float(accuracy_score(y_true, (proba >= DEFAULT_THRESHOLD).astype("int64"))),
        "roc_auc": float(roc_auc_score(y_true, proba)),
    }


def fit_and_score(model, X_train, y_train, X_test, y_test) -> tuple[object, dict[str, float]]:
    """どのモデルでも同じ手順で学習し、同じ指標を測る（比較を公平にするため）。"""
    model.fit(X_train, y_train)
    scores = scores_from_proba(y_test, model.predict_proba(X_test)[:, 1])
    return model, scores


def baseline_scores(y_true) -> dict[str, float]:
    """「全部 高評価」と答えるだけのベースライン。何も学習していない水準の目安。"""
    always_one = np.ones(len(y_true), dtype="int64")
    constant_score = np.full(len(y_true), 0.5)  # 全員同じ点数なので順位が付かない
    return {
        "accuracy": float(accuracy_score(y_true, always_one)),
        "roc_auc": float(roc_auc_score(y_true, constant_score)),
    }


def proba_at(model, X, num_iteration: int) -> np.ndarray:
    """先頭 num_iteration 本の木だけを使った予測確率を返す。

    ブースティングは「足し算の途中経過」を持っているので、学習したあとから本数を
    減らした場合の予測をやり直しの学習なしに再現できます。
    """
    return np.asarray(model.booster_.predict(X, num_iteration=num_iteration), dtype="float64")


def logloss_curve(model, X_train, y_train, X_valid, y_valid, step: int = 2):
    """木の本数を増やしながら訓練データと検証データの対数損失を測る（学習曲線用）。"""
    n_trees = model.booster_.num_trees()
    counts, train_loss, valid_loss = [], [], []
    for k in range(1, n_trees + 1, step):
        counts.append(k)
        train_loss.append(float(log_loss(y_train, proba_at(model, X_train, k), labels=[0, 1])))
        valid_loss.append(float(log_loss(y_valid, proba_at(model, X_valid, k), labels=[0, 1])))
    return counts, train_loss, valid_loss


def tree_leaf_counts(model) -> list[int]:
    """学習した木 1 本ずつの葉の数を取り出す（num_leaves と max_depth の関係を確かめるため）。"""
    return [int(tree["num_leaves"]) for tree in model.booster_.dump_model()["tree_info"]]


def gain_importance(model, names: list[str]) -> pd.DataFrame:
    """gain（その列の分割で減った不純度の合計）で並べた重要度の表を作る。"""
    table = pd.DataFrame(
        {
            "feature": names,
            "gain": model.booster_.feature_importance(importance_type="gain"),
            "split": model.booster_.feature_importance(importance_type="split"),
        }
    )
    return table.sort_values("gain", ascending=False).reset_index(drop=True)


def print_scores(label: str, scores: dict[str, float]) -> None:
    """モデル名・accuracy・ROC AUC を 1 行で表示する。"""
    print(f"{label:<28} accuracy {scores['accuracy']:.4f} / ROC AUC {scores['roc_auc']:.4f}")
