"""セッション 23 の本文・練習問題・解答で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import build_model, cv_auc, load_review_table, split_train_test

    df = load_review_table()
    X_train, X_test, y_train, y_test = split_train_test(df)
    print(cv_auc(build_model(), X_train, y_train))

この章のモデルは **LightGBM で固定**します。探索の対象にする 3 つのパラメータ
（n_estimators・learning_rate・num_leaves）の役割は
「セッション19：勾配ブースティング（LightGBM）」で学んだとおりです。
"""

from __future__ import annotations

from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
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
SCORING = "roc_auc"  # 交差検証・探索で使う指標の名前（scikit-learn の決まった文字列）

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


def build_preprocess() -> ColumnTransformer:
    """数値列を標準化し、カテゴリ列を 0/1 に開く前処理を作る（引数は常に明示する）。"""
    return ColumnTransformer(
        [
            ("num", StandardScaler(), NUMERIC),
            # handle_unknown・sparse_output はバージョンで既定値が変わるので必ず書く
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
        ]
    )


def build_model(**params) -> Pipeline:
    """前処理と LightGBM をひとまとめにしたモデルを作る。

    params には `n_estimators=50` のように **接頭辞なし**で渡します（GridSearchCV に
    渡すときだけ `model__n_estimators` という書き方になります）。何も渡さなければ
    LightGBM の既定値（n_estimators=100・learning_rate=0.1・num_leaves=31）です。

    Pipeline に載せておくと、交差検証の fold ごとに「訓練データだけで fit → 検証
    データは transform だけ」が自動で守られます。組み立て方そのものは
    「セッション25：前処理と学習をひとつにまとめる」で正面から扱います。
    """
    return Pipeline(
        [
            ("pre", build_preprocess()),
            ("model", lgb.LGBMClassifier(random_state=RANDOM_STATE, verbose=-1, **params)),
        ]
    )


def build_linear_model() -> Pipeline:
    """比較用のロジスティック回帰（セッション17 と同じ設定）。"""
    return Pipeline([("pre", build_preprocess()), ("model", LogisticRegression(max_iter=MAX_ITER))])


def features_target(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """特徴量 X と目的変数 y を切り出す（まだ分割しない）。"""
    return df[FEATURES], df["is_high"]


def split_train_test(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """訓練 10,626 件・評価 3,543 件に 1 回だけ分ける（これまでの章と同じ条件）。

    **探索はここで返った X_train・y_train の中だけで行います。** X_test は最後に
    1 回だけ使います。
    """
    X, y = features_target(df)
    return train_test_split(X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)


def stratified_cv() -> StratifiedKFold:
    """層化 5 分割（セッション22 で選んだ分割をそのまま使う）。"""
    return StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)


def cv_auc(model, X: pd.DataFrame, y: pd.Series) -> np.ndarray:
    """交差検証で fold ごとの ROC AUC を測る（fold の数だけ学習する）。"""
    return cross_val_score(model, X, y, cv=stratified_cv(), scoring=SCORING)


def test_auc(model, X_test: pd.DataFrame, y_test: pd.Series) -> float:
    """学習済みモデルをテストデータで測る（**呼ぶのは最後の 1 回だけ**）。"""
    return float(roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]))


def space_size(space: dict[str, list]) -> int:
    """探索空間の組み合わせ数（各パラメータの候補数の掛け算）。"""
    total = 1
    for values in space.values():
        total *= len(values)
    return total


def fit_count(space: dict[str, list], n_splits: int = N_SPLITS, n_iter: int | None = None) -> int:
    """交差検証つき探索で何回 fit するかを数える（組み合わせ数 × fold 数）。"""
    size = space_size(space)
    if n_iter is not None:
        size = min(size, n_iter)
    return size * n_splits


def strip_prefix(params: dict) -> dict:
    """`model__num_leaves` のような接頭辞を落として読みやすくする。"""
    return {key.split("__")[-1]: value for key, value in params.items()}


def results_table(search) -> list[dict]:
    """cv_results_ を「成績の良い順に並べた表」に変える。"""
    results = search.cv_results_
    rows = []
    for params, mean, std, rank in zip(
        results["params"], results["mean_test_score"], results["std_test_score"], results["rank_test_score"]
    ):
        row = strip_prefix(params)
        row["mean"] = float(mean)
        row["std"] = float(std)
        row["rank"] = int(rank)
        rows.append(row)
    return sorted(rows, key=lambda row: (row["rank"], -row["mean"]))


def format_params(params: dict) -> str:
    """パラメータの組を 1 行に並べる（表示の順序を固定するため自前で書く）。"""
    order = ["learning_rate", "n_estimators", "num_leaves"]
    plain = strip_prefix(params)
    return " / ".join(f"{key}={plain[key]}" for key in order if key in plain)


def summarize(scores) -> tuple[float, float]:
    """平均と標準偏差（ddof=0。5 つの fold そのもののばらつき）を返す。"""
    array = np.asarray(scores, dtype="float64")
    return float(array.mean()), float(array.std())


def fmt_scores(scores) -> str:
    """fold ごとのスコアを 1 行に並べる。"""
    return " ".join(f"{float(s):.4f}" for s in scores)


def save_figure(fig, name: str) -> Path:
    """図を outputs/ に保存してパスを返す（MPLBACKEND=Agg なので plt.show は使わない）。"""
    import matplotlib.pyplot as plt  # 図を描くスクリプトだけが必要とするので関数の中で読み込む

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
