"""セッション 18 の本文・練習問題・解答で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import load_review_table, make_forest, pipeline_for, split_xy

    X_train, X_test, y_train, y_test = split_xy(load_review_table())
    forest = pipeline_for(make_forest()).fit(X_train, y_train)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# 高評価レビューの分類に使う特徴量（src/verify_setup.py の 5 節・前章までと同じ）
NUMERIC = ["unit_price", "pages", "published_year", "body_length"]
CATEGORICAL = ["category"]
FEATURES = NUMERIC + CATEGORICAL
TARGET = "is_high"

# 分割とモデルの条件は全章で共通（本書の規約）
TEST_SIZE = 0.25
RANDOM_STATE = 42
MAX_ITER = 1000  # ロジスティック回帰の反復回数（少ないと収束しない）
N_ESTIMATORS = 200  # 木の本数。セッション17・19 と同じ条件にそろえる
N_JOBS = 1  # 並列数は 1 に固定する（再現性のため）

# 決定木の深さをどこまで試すか。None は「深さの制限なし」
DEPTHS: list[int | None] = [1, 2, 3, 5, 10, 20, None]
SHOWCASE_DEPTH = 3  # 図と重要度の比較に使う「浅い木」の深さ

# ID は数値に見えても文字列として読む（先頭の 0 が落ちないようにする）
ID_COLUMNS = {"review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str"}


# ------------------------------------------------------------------
# データの読み込みと分割（前章までとまったく同じ作り方・同じ並び）
# ------------------------------------------------------------------
def load_review_table() -> pd.DataFrame:
    """高評価レビューの分類に使う表を作る（src/verify_setup.py の 5 節と同じ）。

    星が欠損している 298 件を落とし、書籍マスタと注文の単価を結合して 14,169 行にします。
    **並べ替えません。** sort_values を挟むと同じ random_state でも別の分割になります（本書の規約）。
    """
    books = pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"})
    reviews = pd.read_csv(DATA_DIR / "reviews.csv", dtype=ID_COLUMNS)
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
    df[TARGET] = (df["rating"] >= 4).astype("int64")  # 星 4 以上を「高評価」とする
    return df


def split_xy(df: pd.DataFrame):
    """特徴量と目的変数を切り出して訓練・評価に分ける（条件は全章共通）。"""
    X = df[FEATURES]
    y = df[TARGET]
    return train_test_split(X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)


def build_preprocess() -> ColumnTransformer:
    """数値 4 列を標準化し、category を 0/1 の 5 列に開く（引数は常に明示する）。"""
    return ColumnTransformer(
        [
            ("num", StandardScaler(), NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
        ]
    )


def pipeline_for(model) -> Pipeline:
    """前処理とモデルを 1 本にまとめる。比べるモデルの間で前処理を変えないため。

    木モデルは標準化しても結果が変わりません（大小関係が変わらないため）が、
    「条件は特徴量以外すべて同じ」を守るために同じ前処理に載せます。
    """
    return Pipeline([("pre", build_preprocess()), ("model", model)])


def raw_feature_names(pipeline: Pipeline) -> list[str]:
    """前処理後の列名をそのまま返す（num__unit_price / cat__category_小説 の形）。"""
    return [str(name) for name in pipeline.named_steps["pre"].get_feature_names_out()]


def feature_names(pipeline: Pipeline) -> list[str]:
    """接頭辞（num__ / cat__）を落とした読みやすい列名を返す。"""
    return [name.split("__")[-1] for name in raw_feature_names(pipeline)]


# ------------------------------------------------------------------
# モデルの用意と評価
# ------------------------------------------------------------------
def make_tree(max_depth: int | None) -> DecisionTreeClassifier:
    """決定木を 1 本作る。random_state は必ず渡す（同じ分岐を再現するため）。"""
    return DecisionTreeClassifier(max_depth=max_depth, random_state=RANDOM_STATE)


def make_forest(n_estimators: int = N_ESTIMATORS) -> RandomForestClassifier:
    """ランダムフォレストを作る。本数・乱数・並列数をすべて明示する。"""
    return RandomForestClassifier(
        n_estimators=n_estimators,
        random_state=RANDOM_STATE,
        n_jobs=N_JOBS,
    )


def evaluate(pipeline: Pipeline, X_eval, y_eval) -> dict[str, float]:
    """学習済みのパイプラインを評価して accuracy と ROC AUC を返す。"""
    proba = pipeline.predict_proba(X_eval)[:, 1]
    return {
        "accuracy": float(accuracy_score(y_eval, pipeline.predict(X_eval))),
        "roc_auc": float(roc_auc_score(y_eval, proba)),
    }


def fit_and_evaluate(model, X_train, y_train, X_eval, y_eval) -> tuple[Pipeline, dict[str, float]]:
    """学習して (パイプライン, スコア) を返す。条件は全モデルで同じにする。"""
    pipeline = pipeline_for(model).fit(X_train, y_train)
    return pipeline, evaluate(pipeline, X_eval, y_eval)


def baseline_scores(y_eval) -> dict[str, float]:
    """多数クラス（高評価）をそのまま答えるだけのベースライン。

    全員に同じ点数を付けるので順位が付かず、ROC AUC はちょうど 0.5000 になります。
    """
    always_one = np.ones(len(y_eval), dtype="int64")
    constant = np.full(len(y_eval), 0.5)  # 全員同じ点数なので順位が付かない
    return {
        "accuracy": float(accuracy_score(y_eval, always_one)),
        "roc_auc": float(roc_auc_score(y_eval, constant)),
    }


def depth_label(depth: int | None) -> str:
    """深さの表示名。None は「制限なし」と書く。"""
    return "制限なし" if depth is None else str(depth)


def tree_scores(depth: int | None, X_train, y_train, X_eval, y_eval) -> dict:
    """深さを指定した決定木を学習し、葉の数・訓練と評価のスコアを返す。"""
    pipeline = pipeline_for(make_tree(depth)).fit(X_train, y_train)
    tree = pipeline.named_steps["model"]
    return {
        "depth": depth,
        "label": depth_label(depth),
        "leaves": int(tree.get_n_leaves()),
        "nodes": int(tree.tree_.node_count),
        "train_auc": float(roc_auc_score(y_train, pipeline.predict_proba(X_train)[:, 1])),
        "test_auc": float(roc_auc_score(y_eval, pipeline.predict_proba(X_eval)[:, 1])),
        "test_accuracy": float(accuracy_score(y_eval, pipeline.predict(X_eval))),
    }


def depth_table(X_train, y_train, X_eval, y_eval, depths: list[int | None] | None = None) -> list[dict]:
    """DEPTHS の順に決定木を学習して、結果を 1 行 1 辞書で集める。"""
    return [tree_scores(depth, X_train, y_train, X_eval, y_eval) for depth in (depths or DEPTHS)]


def importance_table(pipeline: Pipeline) -> pd.DataFrame:
    """feature_importances_ を列名付きの表にする（**並べ替えない**）。

    並べ替えずに返すのは、別のモデルの重要度と位置で突き合わせられるようにするためです。
    表示するときだけ sort_values を掛けてください。
    """
    return pd.DataFrame(
        {
            "feature": feature_names(pipeline),
            "importance": [float(v) for v in pipeline.named_steps["model"].feature_importances_],
        }
    )


def pad(label: str, width: int = 22) -> str:
    """表の見た目をそろえるために、全角を 2 文字ぶんとして数えて右に空白を足す。"""
    display = sum(2 if ord(char) > 0x2E80 else 1 for char in label)
    return label + " " * max(width - display, 0)


# ------------------------------------------------------------------
# 不純度を手で計算するための小さな表（20 件）
# ------------------------------------------------------------------
# (書籍番号, カテゴリ, 単価, レビュー本文の長さ, 高評価か)
TOY_ROWS: list[tuple[int, str, int, int, int]] = [
    (1, "実用書", 2400, 180, 0),
    (2, "実用書", 2600, 200, 0),
    (3, "実用書", 2200, 100, 0),
    (4, "実用書", 1800, 90, 0),
    (5, "実用書", 1500, 60, 1),
    (6, "技術書", 3400, 220, 0),
    (7, "技術書", 3800, 240, 0),
    (8, "小説", 900, 50, 1),
    (9, "小説", 850, 40, 1),
    (10, "児童書", 1100, 70, 1),
    (11, "児童書", 1000, 55, 1),
    (12, "小説", 950, 80, 1),
    (13, "ビジネス", 1700, 95, 1),
    (14, "児童書", 1200, 65, 1),
    (15, "小説", 1000, 140, 1),
    (16, "児童書", 1300, 160, 1),
    (17, "ビジネス", 1900, 130, 1),
    (18, "技術書", 3200, 110, 1),
    (19, "技術書", 2800, 170, 1),
    (20, "ビジネス", 2500, 190, 1),
]

TOY_COLUMNS = ["book_no", "category", "unit_price", "body_length", TARGET]


def toy_frame() -> pd.DataFrame:
    """不純度の計算を手でたどるための 20 件の表を作る（値は定数なので毎回同じ）。"""
    return pd.DataFrame(TOY_ROWS, columns=TOY_COLUMNS)


def toy_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """トイ例を決定木に渡せる形にする（数値 2 列 ＋ カテゴリを 0/1 に開いた 5 列）。"""
    dummies = pd.get_dummies(df["category"], prefix="category", dtype="int64")
    return pd.concat([df[["unit_price", "body_length"]], dummies], axis=1)


def gini(labels) -> float:
    """ジニ係数（不純度）。0 なら混ざりなし、0.5 が 2 クラスで最も混ざった状態。"""
    values = list(labels)
    if not values:
        return 0.0
    p = sum(values) / len(values)
    return float(1.0 - p**2 - (1.0 - p) ** 2)


def split_gain(df: pd.DataFrame, name: str, mask) -> dict:
    """「条件を満たす側」と「満たさない側」に分けて、ジニ係数の減少量を求める。"""
    total = len(df)
    left = df.loc[mask, TARGET]
    right = df.loc[~mask, TARGET]
    parent = gini(df[TARGET])
    gini_left, gini_right = gini(left), gini(right)
    weighted = (len(left) / total) * gini_left + (len(right) / total) * gini_right
    return {
        "name": name,
        "n_left": len(left),
        "high_left": int(left.sum()),
        "low_left": len(left) - int(left.sum()),
        "gini_left": gini_left,
        "n_right": len(right),
        "high_right": int(right.sum()),
        "low_right": len(right) - int(right.sum()),
        "gini_right": gini_right,
        "weighted": weighted,
        "decrease": parent - weighted,
    }


def toy_candidates(df: pd.DataFrame) -> list[dict]:
    """本文で比べる 4 つの候補の分岐。①〜③は「人が思いつく境目」、④は木が選ぶ境目。"""
    return [
        split_gain(df, "① unit_price <= 2000", df["unit_price"] <= 2000),
        split_gain(df, "② body_length <= 120", df["body_length"] <= 120),
        split_gain(df, "③ category == 実用書", df["category"] == "実用書"),
        split_gain(df, "④ unit_price <= 1750", df["unit_price"] <= 1750),
    ]


def root_split_of(matrix: pd.DataFrame, labels) -> dict:
    """深さ 1 の決定木を学習して、scikit-learn が選んだ根の分岐を取り出す。"""
    tree = make_tree(max_depth=1).fit(matrix, labels)
    inner = tree.tree_
    n_total = inner.n_node_samples[0]
    left, right = inner.children_left[0], inner.children_right[0]
    weighted = (
        inner.n_node_samples[left] / n_total * inner.impurity[left]
        + inner.n_node_samples[right] / n_total * inner.impurity[right]
    )
    return {
        "feature": matrix.columns[inner.feature[0]],
        "threshold": float(inner.threshold[0]),
        "parent_gini": float(inner.impurity[0]),
        "decrease": float(inner.impurity[0] - weighted),
    }
