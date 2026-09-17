"""セッション 15 の本文・練習問題・解答で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import fit_and_score, load_review_features, split_features

    X_train, X_test, y_train, y_test = split_features(load_review_features())
    print(fit_and_score(LogisticRegression(max_iter=1000), X_train, y_train, X_test, y_test))
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import accuracy_score, log_loss, roc_auc_score
from sklearn.model_selection import learning_curve, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# 高評価レビューの分類に使う特徴量（src/verify_setup.py の 5 節・前章までと同じ）
NUMERIC_FEATURES = ["unit_price", "pages", "published_year", "body_length"]
CATEGORY_FEATURE = "category"
FEATURES = NUMERIC_FEATURES + [CATEGORY_FEATURE]
TARGET = "is_high"

# 分割とモデルの条件は全章で共通（本書の規約）
TEST_SIZE = 0.25
VALID_SIZE = 0.20  # 3 分割にするとき、訓練データから検証データへ回す割合
RANDOM_STATE = 42
MAX_ITER = 1000  # ロジスティック回帰の反復回数（少ないと収束しない）

# 学習曲線の条件（この章の中で固定して使う）
TRAIN_SIZES = [0.05, 0.2, 0.5, 1.0]
CV_FOLDS = 5

# 決定木の深さをどこまで試すか。None は「深さの制限なし」
DEPTHS: list[int | None] = [1, 2, 3, 5, 10, 20, None]

# ID は数値に見えても文字列として読む（先頭の 0 が落ちないようにする）
ID_COLUMNS = {"review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str"}


def load_review_features() -> pd.DataFrame:
    """高評価レビューの分類に使う表を作る（前章までと同じ作り方・同じ行の並び）。

    星の欠損 298 件を落とした 14,169 行に書籍マスタと注文の単価を結合し、
    「星 4 以上かどうか」の 0/1 の列（is_high）を足して返します。
    """
    reviews = pd.read_csv(DATA_DIR / "reviews.csv", dtype=ID_COLUMNS)
    books = pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"})
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
    df[TARGET] = (df["rating"] >= 4).astype("int64")
    # 並べ替えない。sort_values を挟むと同じ random_state でも別の分割になる（本書の規約）
    return df


def split_features(df: pd.DataFrame):
    """訓練と評価の 2 分割。本書の演習はこの 2 分割で進める（検証は交差検証に任せる）。"""
    X = df[FEATURES]
    y = df[TARGET]
    return train_test_split(X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)


def split_three_way(df: pd.DataFrame):
    """訓練・検証・テストの 3 分割。**テストを先に取り分けてから**訓練を割る。

    返り値は ((X_fit, y_fit), (X_valid, y_valid), (X_test, y_test)) の 3 組です。
    """
    X_train, X_test, y_train, y_test = split_features(df)
    X_fit, X_valid, y_fit, y_valid = train_test_split(
        X_train,
        y_train,
        test_size=VALID_SIZE,
        random_state=RANDOM_STATE,
        stratify=y_train,  # 正例率をそろえたまま分ける
    )
    return (X_fit, y_fit), (X_valid, y_valid), (X_test, y_test)


def build_preprocess() -> ColumnTransformer:
    """数値 4 列を標準化し、category を One-Hot で開く（前章までと同じ前処理）。"""
    return ColumnTransformer(
        [
            ("num", StandardScaler(), NUMERIC_FEATURES),
            # 引数は常に明示する（既定値はバージョンによって変わる）
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), [CATEGORY_FEATURE]),
        ]
    )


def pipeline_for(model) -> Pipeline:
    """前処理とモデルを 1 本にまとめる。比べるモデルの間で前処理を変えないため。

    決定木は標準化しなくても結果が変わりません（大小関係が変わらないため）が、
    「条件は特徴量以外すべて同じ」を守るために同じ前処理に載せます。
    """
    return Pipeline([("pre", build_preprocess()), ("model", model)])


def fit_and_score(model, X_train, y_train, X_eval, y_eval) -> dict[str, float]:
    """学習して、正解率（accuracy）・ROC AUC・log loss をまとめて返す。"""
    pipeline = pipeline_for(model).fit(X_train, y_train)
    proba = pipeline.predict_proba(X_eval)[:, 1]
    return {
        "accuracy": float(accuracy_score(y_eval, pipeline.predict(X_eval))),
        "roc_auc": float(roc_auc_score(y_eval, proba)),
        "log_loss": float(log_loss(y_eval, proba)),
    }


def pad(label: str, width: int = 26) -> str:
    """表の見た目をそろえるために、全角を 2 文字ぶんとして数えて右に空白を足す。"""
    display = sum(2 if ord(char) > 0x2E80 else 1 for char in label)
    return label + " " * max(width - display, 0)


def depth_label(depth: int | None) -> str:
    """深さの表示名。None は「制限なし」と書く。"""
    return "制限なし" if depth is None else str(depth)


def tree_scores(depth: int | None, X_train, y_train, X_test, y_test) -> dict:
    """深さを指定した決定木を学習し、葉の数・訓練と評価のスコアを返す。"""
    model = DecisionTreeClassifier(max_depth=depth, random_state=RANDOM_STATE)
    pipeline = pipeline_for(model).fit(X_train, y_train)
    tree = pipeline.named_steps["model"]
    return {
        "depth": depth,
        "label": depth_label(depth),
        "leaves": int(tree.get_n_leaves()),
        "train_auc": float(roc_auc_score(y_train, pipeline.predict_proba(X_train)[:, 1])),
        "test_auc": float(roc_auc_score(y_test, pipeline.predict_proba(X_test)[:, 1])),
        "test_accuracy": float(accuracy_score(y_test, pipeline.predict(X_test))),
    }


def depth_table(X_train, y_train, X_test, y_test, depths: list[int | None] | None = None) -> list[dict]:
    """DEPTHS の順に決定木を学習して、結果を 1 行 1 辞書で集める。"""
    return [tree_scores(depth, X_train, y_train, X_test, y_test) for depth in (depths or DEPTHS)]


def learning_curve_of(model, X, y) -> tuple[list[int], list[float], list[float]]:
    """学習曲線を計算して、件数・訓練スコアの平均・検証スコアの平均を返す。

    分割は交差検証（5 分割）なので、1 つの件数につき 5 回学習して平均します。
    """
    sizes, train_scores, valid_scores = learning_curve(
        pipeline_for(model),
        X,
        y,
        train_sizes=TRAIN_SIZES,
        cv=CV_FOLDS,
        scoring="roc_auc",
        # shuffle は既定の False（部分集合は訓練用の行の先頭から順に取られる）。
        # random_state は shuffle=True のときだけ使われますが、本書の規約どおり必ず渡します
        random_state=RANDOM_STATE,
        n_jobs=1,
    )
    return (
        [int(n) for n in sizes],
        [float(v) for v in train_scores.mean(axis=1)],
        [float(v) for v in valid_scores.mean(axis=1)],
    )
