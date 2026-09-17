"""横断復習②（セッション 15 〜 19）の練習問題と解答で共通して使う道具。

C部で身につけた「分割 → 前処理 → 学習 → 評価」を 1 か所に集め直したものです。

    from common import fit_and_score, load_review_table, split_classification

    df = load_review_table()                          # 星が入っているレビュー 14,169 件
    X_train, X_test, y_train, y_test = split_classification(df)

この章のスクリプトはすべて同じディレクトリに置き、他のセッションからは import しません
（読者はこの章のファイルだけを作って実行するため）。
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 画面のないコンテナで図を PNG として保存するための設定
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from matplotlib.figure import Figure
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import learning_curve, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier
from statsmodels.stats.outliers_influence import variance_inflation_factor

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# 分割とモデルの条件は全章で共通（本書の規約）
TEST_SIZE = 0.25
RANDOM_STATE = 42
MAX_ITER = 1000  # ロジスティック回帰の反復回数（少ないと収束しない）
N_ESTIMATORS = 200  # 木の本数。セッション18・19 と同じ条件にそろえる

# 高評価レビューの分類（src/verify_setup.py の 5 節・セッション15 〜 19 と同じ）
NUMERIC_FEATURES = ["unit_price", "pages", "published_year", "body_length"]
CATEGORY_FEATURE = "category"
CLF_FEATURES = NUMERIC_FEATURES + [CATEGORY_FEATURE]
CLF_TARGET = "is_high"

# 星の回帰（セッション16 と同じ。単価ではなく書籍マスタの price を使う点に注意）
REG_FEATURES = ["price", "pages", "published_year", "body_length"]
REG_CORE_FEATURES = ["price", "pages", "body_length"]  # 多重共線性の実演に使う 3 列
REG_TARGET = "rating"

# 決定木の深さをどこまで試すか。None は「深さの制限なし」
DEPTHS: list[int | None] = [1, 3, 5, 10, 20, None]
# 学習曲線の条件（セッション15 と同じ）
TRAIN_SIZES = [0.05, 0.2, 0.5, 1.0]
CV_FOLDS = 5
# 確率をクラスに変える境目。0.5 は既定値であって正解ではない（セッション17）
THRESHOLDS = [0.3, 0.5, 0.7, 0.9]
# 正則化の強さは手で数段階だけ試す（自動探索はセッション23 の仕事）
RIDGE_ALPHAS = [0.1, 100.0]
LASSO_ALPHAS = [0.001, 0.01, 1.0]

# 過学習・未学習の診断に使う線引き（この章の中で固定して使う）
GAP_LIMIT = 0.05  # 訓練 AUC − 評価 AUC がこれを超えたら過学習と呼ぶ
LOW_AUC = 0.70  # 訓練 AUC がこれ未満なら、まだ学習しきれていない（未学習）

# 図のラベルは日本語で書く（本書の方針）
LABEL_JA = {
    "unit_price": "単価",
    "price": "価格",
    "pages": "ページ数",
    "published_year": "刊行年",
    "body_length": "本文の長さ",
    "pages_dup": "ページ数の写し",
}

# ID は数値に見えても文字列として読む（先頭の 0 が落ちないようにする）
ID_COLUMNS = {"review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str"}


# ------------------------------------------------------------------
# 読み込みと分割
# ------------------------------------------------------------------
def load_review_table() -> pd.DataFrame:
    """星が入っているレビュー 14,169 件に書籍マスタと注文の単価を結合して返す。

    **並べ替えません。** train_test_split は行の位置で分割するため、`sort_values` を
    挟むと同じ `random_state=42` でも別の分割になります（本書の規約）。
    分類（`is_high`）と回帰（`rating`）の両方をこの 1 枚の表から作ります。
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
    df[CLF_TARGET] = (df["rating"] >= 4).astype("int64")  # 星 4 以上を「高評価」とする
    return df


def split_classification(df: pd.DataFrame):
    """分類の 2 分割。正例率をそろえるため `stratify=y` を付ける（セッション15）。"""
    X, y = df[CLF_FEATURES], df[CLF_TARGET]
    return train_test_split(X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)


def split_regression(df: pd.DataFrame, features: list[str] | None = None):
    """回帰の 2 分割。目的変数が連続値なので層化はしない（セッション16）。"""
    columns = REG_FEATURES if features is None else features
    return train_test_split(
        df[columns], df[REG_TARGET], test_size=TEST_SIZE, random_state=RANDOM_STATE
    )


# ------------------------------------------------------------------
# 前処理とモデル（分類）
# ------------------------------------------------------------------
def build_preprocess() -> ColumnTransformer:
    """数値 4 列を標準化し、category を 0/1 の 5 列に開く（引数は常に明示する）。"""
    return ColumnTransformer(
        [
            ("num", StandardScaler(), NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), [CATEGORY_FEATURE]),
        ]
    )


def pipeline_for(model) -> Pipeline:
    """前処理とモデルを 1 本にまとめる。比べるモデルの間で前処理を変えないため。"""
    return Pipeline([("pre", build_preprocess()), ("model", model)])


def fitted_feature_names(pipeline: Pipeline) -> list[str]:
    """学習済み Pipeline の列名（`num__` / `cat__` の接頭辞を落としたもの）。"""
    return [name.split("__")[-1] for name in pipeline.named_steps["pre"].get_feature_names_out()]


def score_pipeline(pipeline: Pipeline, X_eval, y_eval) -> dict[str, float]:
    """学習済みの Pipeline を評価する（accuracy・ROC AUC・対数損失）。"""
    proba = pipeline.predict_proba(X_eval)
    return {
        "accuracy": float(accuracy_score(y_eval, pipeline.predict(X_eval))),
        "roc_auc": float(roc_auc_score(y_eval, proba[:, 1])),
        "log_loss": float(log_loss(y_eval, proba)),
    }


def fit_and_score(model, X_train, y_train, X_eval, y_eval) -> dict[str, float]:
    """学習して accuracy・ROC AUC・対数損失をまとめて返す（閾値は既定の 0.5）。"""
    return score_pipeline(pipeline_for(model).fit(X_train, y_train), X_eval, y_eval)


def fit_pipeline(model, X_train, y_train) -> Pipeline:
    """Pipeline に載せて学習し、学習済みの Pipeline そのものを返す。"""
    return pipeline_for(model).fit(X_train, y_train)


def positive_proba(pipeline: Pipeline, X) -> np.ndarray:
    """陽性（高評価）の確率だけを取り出す。列の順番は `classes_` と同じ。"""
    return pipeline.predict_proba(X)[:, 1]


def logistic_coefficients(pipeline: Pipeline) -> pd.Series:
    """ロジスティック回帰の係数を列名付きで返す（標準化後の尺度）。"""
    return pd.Series(pipeline.named_steps["model"].coef_[0], index=fitted_feature_names(pipeline))


def importance_series(pipeline: Pipeline) -> pd.Series:
    """木モデルの `feature_importances_` を列名付きで返す。"""
    return pd.Series(
        pipeline.named_steps["model"].feature_importances_, index=fitted_feature_names(pipeline)
    )


def category_columns(names: list[str]) -> list[str]:
    """One-Hot で開いたカテゴリ列の名前だけを取り出す。"""
    return [name for name in names if name.startswith(f"{CATEGORY_FEATURE}_")]


# ------------------------------------------------------------------
# 評価（分類）
# ------------------------------------------------------------------
def threshold_metrics(y_true, proba, threshold: float) -> dict[str, float]:
    """閾値を 1 つ決めて、適合率・再現率・F1・accuracy を返す（セッション17）。"""
    y_pred = (proba >= threshold).astype("int64")
    return {
        "threshold": float(threshold),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
    }


def threshold_table(y_true, proba, thresholds: list[float] | None = None) -> pd.DataFrame:
    """複数の閾値について `threshold_metrics` を並べた表を作る。"""
    targets = THRESHOLDS if thresholds is None else thresholds
    return pd.DataFrame([threshold_metrics(y_true, proba, t) for t in targets])


def depth_label(depth: int | None) -> str:
    """深さの表示名。None は「制限なし」と書く。"""
    return "制限なし" if depth is None else str(depth)


def diagnose(train_auc: float, test_auc: float) -> str:
    """訓練と評価のスコアから、未学習・釣り合い・過学習のどれかを言い当てる。

    線引き（`LOW_AUC` と `GAP_LIMIT`）は自分で決めた約束です。数値そのものより
    「訓練だけが高いのか、両方低いのか」を見る順番が大事です（セッション15）。
    """
    if train_auc < LOW_AUC:
        return "未学習（バイアスが大きい）"
    if train_auc - test_auc > GAP_LIMIT:
        return "過学習（バリアンスが大きい）"
    return "釣り合っている"


def tree_scores(depth: int | None, X_train, y_train, X_test, y_test) -> dict:
    """深さを指定した決定木を学習し、葉の数・訓練と評価の AUC・診断を返す。"""
    pipeline = fit_pipeline(
        DecisionTreeClassifier(max_depth=depth, random_state=RANDOM_STATE), X_train, y_train
    )
    train_auc = float(roc_auc_score(y_train, positive_proba(pipeline, X_train)))
    test_auc = float(roc_auc_score(y_test, positive_proba(pipeline, X_test)))
    return {
        "depth": depth,
        "label": depth_label(depth),          # None のときだけ「制限なし」と表示する
        "leaves": int(pipeline.named_steps["model"].get_n_leaves()),
        "train_auc": train_auc,
        "test_auc": test_auc,
        "diagnosis": diagnose(train_auc, test_auc),
    }


def depth_table(X_train, y_train, X_test, y_test, depths: list[int | None] | None = None) -> list[dict]:
    """`DEPTHS` の順に決定木を学習して、結果を 1 行 1 辞書で集める。"""
    return [tree_scores(depth, X_train, y_train, X_test, y_test) for depth in (depths or DEPTHS)]


def learning_curve_of(model, X, y) -> dict:
    """学習曲線を計算して、件数・訓練スコアの平均・検証スコアの平均を返す。

    1 つの件数につき 5 分割の交差検証を回すので、5 回学習した平均が入ります。
    """
    sizes, train_scores, valid_scores = learning_curve(
        pipeline_for(model),
        X,
        y,
        train_sizes=TRAIN_SIZES,
        cv=CV_FOLDS,
        scoring="roc_auc",
        # shuffle は既定の False。random_state は shuffle=True のときだけ使われますが、
        # 本書の規約どおり必ず渡します
        random_state=RANDOM_STATE,
        n_jobs=1,
    )
    return {
        "sizes": [int(n) for n in sizes],
        "train": [float(v) for v in train_scores.mean(axis=1)],
        "valid": [float(v) for v in valid_scores.mean(axis=1)],
    }


# ------------------------------------------------------------------
# 線形回帰まわり（セッション16 で書いたものと同じ内容）
# ------------------------------------------------------------------
def fit_linear(X_train: pd.DataFrame, y_train: pd.Series) -> LinearRegression:
    """最小二乗法で超平面を 1 枚あてる。設定するものは何もない。"""
    return LinearRegression().fit(X_train, y_train)


def coef_series(model, columns) -> pd.Series:
    """係数に列名を付けて返す。位置（0 番目、1 番目…）で読むと必ず取り違える。"""
    return pd.Series(model.coef_, index=list(columns))


def regression_scores(model, X_test: pd.DataFrame, y_test: pd.Series) -> dict[str, float]:
    """評価データでの R2・MAE・RMSE を返す。"""
    pred = model.predict(X_test)
    return {
        "r2": float(r2_score(y_test, pred)),
        "mae": float(mean_absolute_error(y_test, pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_test, pred))),
    }


def standardize(X_train: pd.DataFrame, X_test: pd.DataFrame):
    """訓練データだけで平均と標準偏差を決め、両方を同じ尺度に直す（列名は保つ）。"""
    scaler = StandardScaler().fit(X_train)  # fit は訓練データだけ（セッション12 の規約）
    X_train_s = pd.DataFrame(scaler.transform(X_train), columns=X_train.columns, index=X_train.index)
    X_test_s = pd.DataFrame(scaler.transform(X_test), columns=X_test.columns, index=X_test.index)
    return X_train_s, X_test_s, scaler


def fit_ols(X: pd.DataFrame, y: pd.Series):
    """statsmodels の最小二乗法。**切片の列を自分で足す**のを忘れないこと。"""
    return sm.OLS(y, sm.add_constant(X)).fit()


def vif_table(X: pd.DataFrame) -> pd.Series:
    """VIF（分散拡大係数）を列名付きで返す。切片の列を足した行列に対して計算する。"""
    exog = sm.add_constant(X).to_numpy(dtype="float64")
    names = ["const"] + list(X.columns)
    values = [variance_inflation_factor(exog, i) for i in range(exog.shape[1])]
    return pd.Series(values, index=names).drop("const")  # 切片自身の VIF は読まない


def add_pages_dup(df: pd.DataFrame) -> pd.DataFrame:
    """pages とほとんど同じ情報しか持たない列を 1 本足す（多重共線性の実演用）。"""
    out = df.copy()
    rng = np.random.default_rng(RANDOM_STATE)  # 何度実行しても同じノイズになる
    out["pages_dup"] = out["pages"] * 6 + rng.normal(0, 1, len(out))
    return out


def fit_penalized(model, X_train_s: pd.DataFrame, y_train, X_test_s: pd.DataFrame, y_test):
    """Ridge / Lasso を学習し、係数（列名付き）と評価データの R2 を返す。"""
    model.fit(X_train_s, y_train)
    return coef_series(model, X_train_s.columns), float(r2_score(y_test, model.predict(X_test_s)))


def zero_columns(coefs: pd.Series) -> list[str]:
    """係数がちょうど 0 になった列の名前（Lasso の変数選択の結果を読むため）。"""
    return [str(name) for name, value in coefs.items() if value == 0.0]


def vif_display(value: float) -> str:
    """VIF の表示。桁が大きくなったら小数を出さない（読めなくなるため）。"""
    return f"{value:,.3f}" if value < 1000 else f"{value:,.0f}"


def fmt_p(p: float) -> str:
    """p 値の表示。小さい値は指数表記にする（0.0000 と書くと誤解を招く）。"""
    return f"{p:.4f}" if p >= 0.001 else f"{p:.2e}"


def save_fig(fig: Figure, name: str) -> None:
    """図を outputs/ に保存し、保存先を表示してから Figure を閉じる。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_DIR / name, dpi=110, bbox_inches="tight")
    plt.close(fig)  # 閉じないと Figure が開いたまま溜まっていく
    print(f"図を保存しました: outputs/{name}")
