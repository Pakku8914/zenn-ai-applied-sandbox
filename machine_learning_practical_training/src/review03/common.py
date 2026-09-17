"""横断復習③（セッション 20 〜 28）の練習問題と解答で共通して使う道具。

同じディレクトリのスクリプトから次のように使います。

    from common import high_bundle, leak_experiments, psi_table

    bundle = high_bundle()          # 高評価分類（ロジスティック回帰）の予測確率
    rows = leak_experiments()       # 4 種類のリークを「正しい手順」と並べた表
    print(psi_table())              # 監視に使う 4 列の PSI

D部・E部で身につけた「指標を選ぶ → 検証を組む → リークを点検する → 解釈する →
監視を設計する」の道具を 1 か所に集め直したものです。読み込みと分割の条件は
`src/verify_setup.py` の 5 節・6 節とまったく同じで、**行を並べ替えません**
（`sort_values` を挟むと同じ `random_state=42` でも別の分割になります）。

`lru_cache` を付けた関数の返り値は**書き換えないでください**（呼び出し側で共有します）。
列を足したいときは `load_review_table().assign(...)` のようにコピーを作ってください。

このディレクトリのスクリプトは、他のセッションのディレクトリを一切参照しません
（読者がこの章のファイルだけを作って実行できるようにするためです）。
"""

from __future__ import annotations

import warnings
from functools import lru_cache
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 画面のないコンテナで図を PNG として保存するための設定
import lightgbm as lgb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap
from matplotlib.figure import Figure
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.impute import SimpleImputer
from sklearn.inspection import partial_dependence, permutation_importance
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    mean_absolute_error,
    mean_absolute_percentage_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
    roc_curve,
    root_mean_squared_error,
)
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
MAX_ITER = 1000          # ロジスティック回帰の反復上限
N_ESTIMATORS = 200       # LightGBM の木の本数
N_SPLITS = 5             # 交差検証の fold 数
SCORING = "roc_auc"      # 交差検証で使う指標の名前（scikit-learn の決まった文字列）
TOLERANCE = 0.005        # 本書の許容誤差。これ未満の差は「差が出ていない」と扱う

# ID は数値に見えても文字列として読む（先頭の 0 が落ちないようにする）
ID_COLUMNS = {"review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str"}

# ------------------------------------------------------------------
# 高評価レビューの分類（セッション17 〜 26 と同じ 5 列）
# ------------------------------------------------------------------
HIGH_NUMERIC = ["unit_price", "pages", "published_year", "body_length"]
HIGH_CATEGORICAL = ["category"]
HIGH_FEATURES = HIGH_NUMERIC + HIGH_CATEGORICAL
HIGH_TARGET = "is_high"
BEFORE_POSTING = ["unit_price", "pages", "published_year"]  # 投稿前に分かっている列（S22）
WIDE_CATEGORICAL = ["category", "region", "channel"]        # Pipeline の最終形（S25）

POSITIVE_LABEL = 1
NEGATIVE_LABEL = 0
HIGH_CLASS_NAMES = {NEGATIVE_LABEL: "陰性（低評価）", POSITIVE_LABEL: "陽性（高評価）"}
DEFAULT_THRESHOLD = 0.5
COST_GRID = np.round(np.arange(0.05, 1.00, 0.05), 2)  # コストから閾値を決める刻み
COST_SETTINGS = [(1, 1), (5, 1), (1, 5)]              # (見逃し 1 件の重み, 誤検出 1 件の重み)

# ------------------------------------------------------------------
# 星の回帰（セッション21）
# ------------------------------------------------------------------
REG_TARGET = "rating"
LINEAR = "線形回帰"
LGBM = "LightGBM"
MEAN = "平均予測"
MODEL_ORDER = [LINEAR, LGBM, MEAN]
METRIC_KEYS = ["mae", "rmse", "mape", "r2"]
CONSTANT_GUESS = 3.0     # 「全部 3.0」と答えるだけのモデル（R2 が負になる例）
OUTLIER_STAR = 10.0      # 星 10 という実在しない値（外れ値の影響を測る実験用）
STARS = [3.0, 4.0, 5.0]  # 残差を星ごとに見るときに使う（星 1・星 2 は件数が少なすぎる）

# ------------------------------------------------------------------
# キャンセル予測（セッション24・28）
# ------------------------------------------------------------------
CANCEL_NUMERIC = ["unit_price", "quantity", "discount_rate", "days_since_signup"]
CANCEL_CATEGORICAL = ["channel"]
CANCEL_FEATURES = CANCEL_NUMERIC + CANCEL_CATEGORICAL
CANCEL_THRESHOLDS = [0.1, 0.3, 0.5]
CANCEL_KINDS = ("plain", "balanced", "under")
KIND_NAMES = {
    "plain": "重みなし",
    "balanced": 'class_weight="balanced"',
    "under": "1:1 アンダーサンプリング",
}

# ------------------------------------------------------------------
# リークの実験（セッション13・22）
# ------------------------------------------------------------------
N_NOISE = 500      # 中身が乱数だけの列の本数
K_SELECT = 10      # そのうち「効きそうな」何列を残すか
CHANCE_AUC = 0.5   # 二値分類の当て推量
ID_FEATURE = "book_id"
# セッション14 で測った「全期間のキャンセル数」を足した実験の成績（ここでは学習し直さない）
FUTURE_LEAK_AUC = 0.9664
FUTURE_LEAK_PR_AUC = 0.4969

# ------------------------------------------------------------------
# 解釈（セッション26）
# ------------------------------------------------------------------
RANDOM_ID = "random_id"
RANDOM_ID_MAX = 10000
N_REPEATS = 5            # permutation importance で 1 列を何回シャッフルするか
GRID_RESOLUTION = 5      # 部分依存で 1 列を何点に区切るか
SHAP_N_ESTIMATORS = 50
SHAP_ROWS = 100
PUBLISHED_YEAR_P_VALUE = 0.2425  # セッション16 で statsmodels が出した p 値（引用）

# ------------------------------------------------------------------
# 監視（セッション28）
# ------------------------------------------------------------------
AS_OF = pd.Timestamp("2026-09-01")       # データの基準日（本書共通）
SPLIT_DATE = pd.Timestamp("2025-09-01")  # ここより前を「学習したころ」、後を「いま」とする
PSI_COLUMNS = ["unit_price", "quantity", "discount_rate", "amount"]
PSI_BINS = 10
PSI_FLOOR = 1e-6         # ゼロ割り・log(0) を避けるために比率をこの値でクリップする
PSI_WATCH = 0.10         # 慣例的な目安: 0.1 未満は安定
PSI_ACT = 0.25           # 0.25 以上は要再学習
DRIFT_RATIOS = (1.00, 1.05, 1.20, 1.50)
QUANTITY_FRACTION = 0.30
QUANTITY_VALUE = 5
MONITOR_MONTHS = 6       # 月次の性能を追う期間
BAND_SIGMA = 2.0         # 平均 ± 何σを「ばらつきの範囲」とするか
SLOPE_LIMIT = -0.005     # 1 か月あたりこれより急に下がっていたら「下降トレンド」
RETRAIN_MAX_DAYS = 180   # 学習データの最終日からこれ以上たったら再学習する
RETRAIN_GROWTH = 2.0     # 学習時の何倍までデータが増えたら再学習するか

LABEL_JA = {
    "unit_price": "単価",
    "pages": "ページ数",
    "published_year": "刊行年",
    "body_length": "本文の長さ",
    "category": "カテゴリ",
    "random_id": "意味のない乱数",
    "quantity": "数量",
    "discount_rate": "値引き率",
    "amount": "売上額",
}


# ==================================================================
# 読み込み
# ==================================================================
@lru_cache(maxsize=None)
def load_review_table() -> pd.DataFrame:
    """高評価レビューの分類に使う表（`src/verify_setup.py` の 5 節と同じ作り方・同じ並び）。

    星の欠損 298 件を落とした 14,169 行に、書籍マスタと注文の単価を結合して返します。
    """
    books = pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"})
    reviews = pd.read_csv(DATA_DIR / "reviews.csv", dtype=ID_COLUMNS, parse_dates=["reviewed_at"])
    orders = pd.read_csv(
        DATA_DIR / "orders.csv", dtype={"order_id": "str"}, usecols=["order_id", "unit_price"]
    )
    df = (
        reviews.dropna(subset=["rating"])  # 星の欠損を落とす（セッション11）
        .merge(books, on="book_id", how="left")
        .merge(orders.drop_duplicates("order_id"), on="order_id", how="left")
    )
    df[HIGH_TARGET] = (df["rating"] >= 4).astype("int64")  # 星 4 以上を「高評価」とする
    return df


@lru_cache(maxsize=None)
def load_wide_review_table() -> pd.DataFrame:
    """上の表に顧客の `region`（欠損あり）と `channel` を足したもの（セッション25 の題材）。"""
    customers = pd.read_csv(
        DATA_DIR / "customers.csv", dtype={"customer_id": "str"}, usecols=["customer_id", "region", "channel"]
    )
    return load_review_table().merge(customers, on="customer_id", how="left")


@lru_cache(maxsize=None)
def load_orders() -> pd.DataFrame:
    """注文 60,031 行（`order_id` の重複 30 件を落としたもの）に売上額を足して返す。

    売上額 `amount` は **行ごとに丸めません**（丸めると章をまたいで金額がずれます）。
    """
    orders = pd.read_csv(DATA_DIR / "orders.csv", dtype=ID_COLUMNS, parse_dates=["ordered_at"])
    orders = orders.drop_duplicates("order_id")
    return orders.assign(amount=orders["unit_price"] * orders["quantity"] * (1 - orders["discount_rate"]))


@lru_cache(maxsize=None)
def load_cancel_table() -> pd.DataFrame:
    """キャンセル予測の表（`src/verify_setup.py` の 6 節・セッション24 と同じ並び）。"""
    customers = pd.read_csv(
        DATA_DIR / "customers.csv",
        dtype={"customer_id": "str"},
        parse_dates=["signup_date"],
        usecols=["customer_id", "channel", "signup_date"],
    )
    df = load_orders().merge(customers, on="customer_id", how="left")
    return df.assign(days_since_signup=(df["ordered_at"] - df["signup_date"]).dt.days)


# ==================================================================
# 前処理とモデル（分類）
# ==================================================================
def build_preprocess(numeric: list[str], categorical: list[str]) -> ColumnTransformer:
    """数値列を標準化し、カテゴリ列を 0/1 に開く（引数は常に明示する）。"""
    return ColumnTransformer(
        [
            ("num", StandardScaler(), numeric),
            # handle_unknown・sparse_output は版によって既定値が変わるので必ず書く
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical),
        ]
    )


def build_logistic(numeric: list[str] | None = None, categorical: list[str] | None = None) -> Pipeline:
    """前処理とロジスティック回帰を 1 本にまとめる（セッション17・25 と同じ設定）。"""
    numeric = HIGH_NUMERIC if numeric is None else numeric
    categorical = HIGH_CATEGORICAL if categorical is None else categorical
    return Pipeline(
        [
            ("pre", build_preprocess(numeric, categorical)),
            ("model", LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)),
        ]
    )


def build_imputing_pipeline(numeric: list[str] | None = None, categorical: list[str] | None = None) -> Pipeline:
    """欠損補完まで Pipeline の中に入れた最終形（セッション25）。`region` の欠損を埋める。"""
    numeric = HIGH_NUMERIC if numeric is None else numeric
    categorical = WIDE_CATEGORICAL if categorical is None else categorical
    numeric_steps = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())])
    categorical_steps = Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    return Pipeline(
        [
            ("pre", ColumnTransformer([("num", numeric_steps, numeric), ("cat", categorical_steps, categorical)])),
            ("model", LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)),
        ]
    )


def build_gbm(**params) -> lgb.LGBMClassifier:
    """LightGBM の分類器（条件は全章共通）。`class_weight` だけ差し替えられるようにする。"""
    return lgb.LGBMClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, verbose=-1, **params)


def split_stratified(X, y):
    """正例率をそろえた 2 分割（分類はすべてこれ）。X の列が何であっても同じ行が評価になる。"""
    return train_test_split(X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)


def split_plain(X, y):
    """層化しない 2 分割（回帰と多クラスはこちら）。"""
    return train_test_split(X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE)


def positive_proba(model, X) -> np.ndarray:
    """陽性クラスの予測確率だけを取り出す。"""
    return model.predict_proba(X)[:, 1]


def clean_names(pre: ColumnTransformer) -> list[str]:
    """`num__` / `cat__` の接頭辞を落とした変換後の列名。"""
    return [name.split("__")[-1] for name in pre.get_feature_names_out()]


@lru_cache(maxsize=None)
def high_bundle() -> dict:
    """高評価分類（ロジスティック回帰・5 特徴量）を学習して結果をまとめる。"""
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_stratified(df[HIGH_FEATURES], df[HIGH_TARGET])
    model = build_logistic().fit(X_train, y_train)
    proba = positive_proba(model, X_test)
    return {
        "model": model,
        "n_rows": int(len(df)),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "rate_train": float(y_train.mean()),
        "rate_test": float(y_test.mean()),
        "y_test": y_test,
        "proba": proba,
        "accuracy": float(accuracy_score(y_test, model.predict(X_test))),
        "roc_auc": float(roc_auc_score(y_test, proba)),
        "pr_auc": float(average_precision_score(y_test, proba)),
        "log_loss": float(log_loss(y_test, model.predict_proba(X_test))),
    }


def holdout_auc(df: pd.DataFrame, numeric: list[str] | None = None, categorical: list[str] | None = None) -> float:
    """正しい手順（分割 → 訓練データだけで fit）で測る ROC AUC。"""
    numeric = HIGH_NUMERIC if numeric is None else numeric
    categorical = HIGH_CATEGORICAL if categorical is None else categorical
    X, y = df[numeric + categorical], df[HIGH_TARGET]
    X_train, X_test, y_train, y_test = split_stratified(X, y)
    model = build_logistic(numeric, categorical).fit(X_train, y_train)
    return float(roc_auc_score(y_test, positive_proba(model, X_test)))


# ==================================================================
# 分類の評価指標（セッション20・24）
# ==================================================================
def predict_at(proba, threshold: float = DEFAULT_THRESHOLD) -> np.ndarray:
    """確率を閾値で切ってクラス（0 / 1）に変える。`predict` は threshold=0.5 と同じ。"""
    return (np.asarray(proba) >= threshold).astype("int64")


def confusion_parts(y_true, y_pred) -> dict[str, int]:
    """混同行列の 4 象限を名前付きで取り出す（labels を明示して並びを固定する）。"""
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[NEGATIVE_LABEL, POSITIVE_LABEL]).ravel()
    return {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}


def class_metrics(y_true, y_pred, label: int) -> dict[str, float]:
    """1 つのクラスを陽性とみなしたときの適合率・再現率・F1・件数。"""
    return {
        "precision": float(precision_score(y_true, y_pred, pos_label=label, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, pos_label=label, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, pos_label=label, zero_division=0)),
        "support": int((np.asarray(y_true) == label).sum()),
    }


def per_class_table(y_true, y_pred) -> pd.DataFrame:
    """陰性・陽性の両方について指標を並べた表（片方だけ見ないための道具）。"""
    rows = []
    for label in (NEGATIVE_LABEL, POSITIVE_LABEL):
        row = {"label": label, "name": HIGH_CLASS_NAMES[label]}
        row.update(class_metrics(y_true, y_pred, label))
        rows.append(row)
    return pd.DataFrame(rows)


def average_scores(y_true, y_pred) -> dict[str, float]:
    """平均の取り方を変えた F1 と accuracy（macro は少数クラスも 1 票）。"""
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro")),
        "weighted_f1": float(f1_score(y_true, y_pred, average="weighted")),
        "micro_f1": float(f1_score(y_true, y_pred, average="micro")),
    }


def majority_baseline(y_true, label: int) -> dict[str, float]:
    """「全部 `label`」と答えるだけのベースライン（多数クラス予測）。"""
    y_array = np.asarray(y_true)
    constant = np.full(len(y_array), float(label))
    scores = np.full(len(y_array), 0.5)  # 全件同じ点数なので順位が付かない
    return {
        "accuracy": float(accuracy_score(y_array, constant.astype("int64"))),
        "roc_auc": float(roc_auc_score(y_array, scores)),
        "pr_auc": float(average_precision_score(y_array, scores)),
        "positive_rate": float(y_array.mean()),
        "n_positive": int(y_array.sum()),
        "n_rows": int(len(y_array)),
    }


def threshold_metrics(y_true, proba, threshold: float) -> dict[str, float]:
    """閾値 1 つぶんの指標。捕まえた件数（TP）と見逃した件数（FN）も返す。"""
    y_pred = predict_at(proba, threshold)
    parts = confusion_parts(y_true, y_pred)
    return {
        "threshold": float(threshold),
        "n_positive": int(parts["fp"] + parts["tp"]),
        "tp": parts["tp"],
        "fn": parts["fn"],
        "fp": parts["fp"],
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
    }


def threshold_table(y_true, proba, thresholds) -> pd.DataFrame:
    """複数の閾値について `threshold_metrics` を並べた表。"""
    return pd.DataFrame([threshold_metrics(y_true, proba, t) for t in thresholds])


def score_summary(y_true, proba, threshold: float = DEFAULT_THRESHOLD) -> dict[str, float]:
    """不均衡データを語るのに必要な指標をまとめて計算する（accuracy は比較用）。"""
    row = threshold_metrics(y_true, proba, threshold)
    return {
        "roc_auc": float(roc_auc_score(y_true, proba)),
        "pr_auc": float(average_precision_score(y_true, proba)),
        "accuracy": row["accuracy"],
        "precision": row["precision"],
        "recall": row["recall"],
        "f1": row["f1"],
        "mean_proba": float(np.mean(np.asarray(proba))),
        "brier": float(brier_score_loss(y_true, proba)),
    }


def youden_point(y_true, proba) -> dict[str, float]:
    """Youden 指標（TPR − FPR）が最大になる点を ROC 曲線の上から探す。"""
    fpr, tpr, thresholds = roc_curve(y_true, proba)
    index = int(np.argmax(tpr - fpr))
    return {
        "threshold": float(thresholds[index]),
        "tpr": float(tpr[index]),
        "fpr": float(fpr[index]),
        "youden": float(tpr[index] - fpr[index]),
    }


def cost_table(y_true, proba, miss_cost: float, alarm_cost: float) -> pd.DataFrame:
    """0.05 刻みの閾値について「見逃し × 重み + 誤検出 × 重み」を並べる。"""
    rows = []
    for threshold in COST_GRID:
        parts = confusion_parts(y_true, predict_at(proba, threshold))
        rows.append(
            {
                "threshold": float(threshold),
                "n_miss": parts["fn"],
                "n_alarm": parts["fp"],
                "total_cost": float(parts["fn"] * miss_cost + parts["fp"] * alarm_cost),
            }
        )
    return pd.DataFrame(rows)


def best_cost_threshold(y_true, proba, miss_cost: float, alarm_cost: float) -> dict[str, float]:
    """総コストが最小になる閾値（同点なら小さい閾値）。"""
    table = cost_table(y_true, proba, miss_cost, alarm_cost)
    row = table.loc[table["total_cost"].idxmin()]
    return {
        "threshold": float(row["threshold"]),
        "n_miss": int(row["n_miss"]),
        "n_alarm": int(row["n_alarm"]),
        "total_cost": float(row["total_cost"]),
    }


def star_stratify_error() -> str:
    """星 1〜5 を `stratify` しようとして出た `ValueError` の文面を返す（実演用）。"""
    df = load_review_table()
    try:
        split_stratified(df[HIGH_FEATURES], df[REG_TARGET].astype("int64"))
    except ValueError as error:
        return str(error)
    raise AssertionError("ValueError が出ませんでした（データが変わった可能性があります）")


@lru_cache(maxsize=None)
def star_multiclass() -> dict:
    """星 1〜5 をそのまま予測する 5 クラス分類（層化できないので層化なしで分ける）。"""
    df = load_review_table()
    y = df[REG_TARGET].astype("int64")
    X_train, X_test, y_train, y_test = split_plain(df[HIGH_FEATURES], y)
    model = build_logistic().fit(X_train, y_train)
    y_pred = model.predict(X_test)
    scores = average_scores(y_test, y_pred)
    scores["n_test"] = int(len(y_test))
    return scores


# ==================================================================
# 回帰の評価指標（セッション21）
# ==================================================================
def regression_pipeline(model) -> Pipeline:
    """前処理（標準化と One-Hot）と回帰モデルを 1 本にまとめる。"""
    return Pipeline([("pre", build_preprocess(HIGH_NUMERIC, HIGH_CATEGORICAL)), ("model", model)])


def regression_models() -> dict[str, Pipeline]:
    """比べる 3 つのモデル。前処理をそろえてあるので条件は完全に同じ。

    平均予測（`DummyRegressor`）は特徴量を一切見ません。前処理を通しているのは
    「同じ手順で扱う」ためだけで、返す値は訓練データの星の平均という定数です。
    """
    return {
        LINEAR: regression_pipeline(LinearRegression()),
        LGBM: regression_pipeline(
            lgb.LGBMRegressor(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, verbose=-1)
        ),
        MEAN: regression_pipeline(DummyRegressor(strategy="mean")),
    }


def regression_scores(y_true, pred) -> dict[str, float]:
    """回帰の 4 指標をまとめて返す。1 つだけ返す関数を作らないのがこの章の主題。"""
    return {
        "mae": float(mean_absolute_error(y_true, pred)),
        "rmse": float(root_mean_squared_error(y_true, pred)),
        "mape": float(mean_absolute_percentage_error(y_true, pred)),
        "r2": float(r2_score(y_true, pred)),
    }


@lru_cache(maxsize=None)
def star_regression() -> dict:
    """星の回帰を 3 モデル同じ分割で学習し、実測・予測・4 指標をまとめて返す。"""
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_plain(df[HIGH_FEATURES], df[REG_TARGET])
    preds: dict[str, np.ndarray] = {}
    for name, model in regression_models().items():
        model.fit(X_train, y_train)
        preds[name] = np.asarray(model.predict(X_test), dtype="float64")
    return {
        "y_test": y_test,
        "preds": preds,
        "scores": {name: regression_scores(y_test, pred) for name, pred in preds.items()},
        "train_mean": float(y_train.mean()),
    }


def best_by(scores: dict[str, dict[str, float]], metric: str) -> str:
    """指標ごとにいちばん良いモデルの名前（R2 だけは大きいほうが良い）。"""
    if metric == "r2":
        return max(scores, key=lambda name: scores[name][metric])
    return min(scores, key=lambda name: scores[name][metric])


def constant_prediction(y_true, value: float) -> np.ndarray:
    """どの行にも同じ値を返すだけの予測（定数モデル）。"""
    return np.full(len(y_true), float(value))


def residual_by_actual(y_true, pred) -> pd.DataFrame:
    """実測の星ごとに、件数・残差（実測 − 予測）の平均・予測の平均を集計する。"""
    table = pd.DataFrame(
        {
            "actual": np.asarray(y_true, dtype="float64"),
            "pred": np.asarray(pred, dtype="float64"),
        }
    )
    table["residual"] = table["actual"] - table["pred"]
    return table.groupby("actual").agg(
        count=("residual", "size"), residual_mean=("residual", "mean"), pred_mean=("pred", "mean")
    )


def outlier_effect(y_true, pred) -> dict[str, dict[str, float]]:
    """先頭 1 件の実測を星 10 に差し替え、MAE と RMSE の動き方を比べる。"""
    swapped = pd.Series(np.asarray(y_true, dtype="float64")).copy()
    swapped.iloc[0] = OUTLIER_STAR
    return {"before": regression_scores(y_true, pred), "after": regression_scores(swapped, pred)}


# ==================================================================
# 交差検証（セッション22・25）
# ==================================================================
def cv_scores(estimator, X, y, cv, groups=None) -> np.ndarray:
    """交差検証で fold ごとの ROC AUC を測る（Pipeline なら fold ごとに fit し直される）。"""
    return cross_val_score(estimator, X, y, cv=cv, groups=groups, scoring=SCORING)


def summarize(scores) -> tuple[float, float]:
    """平均と標準偏差（ddof=0。5 つの fold そのもののばらつき）を返す。"""
    array = np.asarray(scores, dtype="float64")
    return float(array.mean()), float(array.std())


def fmt_scores(scores) -> str:
    """fold ごとのスコアを 1 行に並べる。"""
    return " ".join(f"{float(s):.4f}" for s in scores)


@lru_cache(maxsize=None)
def cv_strategies() -> list[dict]:
    """4 種類の分割（層化・層化なし・グループ・時系列）を同じデータ・同じモデルで比べる。"""
    df = load_review_table()
    X, y = df[HIGH_FEATURES], df[HIGH_TARGET]
    ordered = df.sort_values("reviewed_at")  # 時系列分割だけは時間順に並べてから渡す
    rows = [
        {
            "label": "① 層化 5 分割",
            "scores": cv_scores(
                build_logistic(), X, y, StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
            ),
        },
        {
            "label": "② 層化なし 5 分割",
            "scores": cv_scores(
                build_logistic(), X, y, KFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
            ),
        },
        {
            "label": "③ 顧客単位のグループ分割",
            "scores": cv_scores(
                build_logistic(), X, y, GroupKFold(n_splits=N_SPLITS), groups=df["customer_id"]
            ),
        },
        {
            "label": "④ 時系列分割",
            "scores": cv_scores(
                build_logistic(), ordered[HIGH_FEATURES], ordered[HIGH_TARGET], TimeSeriesSplit(n_splits=N_SPLITS)
            ),
        },
    ]
    for row in rows:
        row["mean"], row["std"] = summarize(row["scores"])
    return rows


@lru_cache(maxsize=None)
def pipeline_bundle() -> dict:
    """欠損補完込みの Pipeline（数値 4 列 + カテゴリ 3 列）をホールドアウトと交差検証で測る。"""
    df = load_wide_review_table()
    X, y = df[HIGH_NUMERIC + WIDE_CATEGORICAL], df[HIGH_TARGET]
    X_train, X_test, y_train, y_test = split_stratified(X, y)
    model = build_imputing_pipeline().fit(X_train, y_train)
    scores = cv_scores(
        build_imputing_pipeline(), X, y, StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    )
    mean, std = summarize(scores)
    return {
        "names": clean_names(model.named_steps["pre"]),
        "n_missing_region": int(df["region"].isna().sum()),
        "test_auc": float(roc_auc_score(y_test, positive_proba(model, X_test))),
        "cv_mean": mean,
        "cv_std": std,
        "scores": scores,
    }


# ==================================================================
# リークの実験（セッション13・22）
# ==================================================================
def scaler_leak_pair(df: pd.DataFrame) -> dict[str, float]:
    """前処理を分割の前に当てる（＝評価データの平均も混ざる）とどうなるか。"""
    X, y = df[HIGH_FEATURES], df[HIGH_TARGET]
    X_all = build_preprocess(HIGH_NUMERIC, HIGH_CATEGORICAL).fit_transform(X)  # 全データで fit
    X_train, X_test, y_train, y_test = split_stratified(X_all, y)
    model = LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE).fit(X_train, y_train)
    return {"correct": holdout_auc(df), "leaked": float(roc_auc_score(y_test, positive_proba(model, X_test)))}


def make_noise(n_rows: int) -> pd.DataFrame:
    """目的変数とまったく関係のない正規乱数の列を 500 本作る。"""
    rng = np.random.default_rng(RANDOM_STATE)
    values = rng.normal(size=(n_rows, N_NOISE))
    return pd.DataFrame(values, columns=[f"noise{i:03d}" for i in range(N_NOISE)])


def noise_leak_pair(df: pd.DataFrame) -> dict[str, float]:
    """雑音 500 列から 10 列を選ぶ手順を、分割の前と後で比べる。"""
    y = df[HIGH_TARGET]
    X_noise = make_noise(len(df))

    # リークする手順: 分割の前に、全データ（＝評価データの答えも）を見て 10 列を選ぶ
    selector = SelectKBest(f_classif, k=K_SELECT).fit(X_noise, y)
    X_selected = X_noise.loc[:, selector.get_support()]
    X_train, X_test, y_train, y_test = split_stratified(X_selected, y)
    leaked_model = LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE).fit(X_train, y_train)
    leaked = float(roc_auc_score(y_test, positive_proba(leaked_model, X_test)))

    # 正しい手順: 分割してから、訓練データだけを見て 10 列を選ぶ（選抜も Pipeline に入れる）
    X_train, X_test, y_train, y_test = split_stratified(X_noise, y)
    honest_model = Pipeline(
        [
            ("select", SelectKBest(f_classif, k=K_SELECT)),
            ("model", LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)),
        ]
    ).fit(X_train, y_train)
    honest = float(roc_auc_score(y_test, positive_proba(honest_model, X_test)))
    return {"correct": honest, "leaked": leaked, "shape": X_noise.shape}


def target_means(keys: pd.Series, y: pd.Series) -> pd.Series:
    """水準ごとの目的変数の平均（ターゲットエンコーディングの対応表）。"""
    return y.groupby(keys).mean()


def target_column(frame: pd.DataFrame, means: pd.Series, prior: float, column: str) -> pd.DataFrame:
    """対応表を当てて 1 本の列にする。表に無い水準は prior（全体の平均）で埋める。"""
    values = frame[column].map(means).fillna(prior).astype("float64")
    return pd.DataFrame({f"{column}_target": values}, index=frame.index)


def target_encoding_pair(df: pd.DataFrame) -> dict[str, float]:
    """`book_id`（600 水準）の対応表を、訓練データだけで作る場合と全データで作る場合で比べる。"""
    X = df[HIGH_NUMERIC + HIGH_CATEGORICAL + [ID_FEATURE]]
    X_train, X_test, y_train, y_test = split_stratified(X, df[HIGH_TARGET])
    scaler = StandardScaler().set_output(transform="pandas").fit(X_train[HIGH_NUMERIC])
    num_train, num_test = scaler.transform(X_train[HIGH_NUMERIC]), scaler.transform(X_test[HIGH_NUMERIC])

    def auc_with(means: pd.Series, prior: float) -> float:
        train = pd.concat([num_train, target_column(X_train, means, prior, ID_FEATURE)], axis=1)
        test = pd.concat([num_test, target_column(X_test, means, prior, ID_FEATURE)], axis=1)
        model = build_gbm().fit(train.to_numpy(), y_train)
        return float(roc_auc_score(y_test, model.predict_proba(test.to_numpy())[:, 1]))

    clean = auc_with(target_means(X_train[ID_FEATURE], y_train), float(y_train.mean()))
    leaked = auc_with(target_means(df[ID_FEATURE], df[HIGH_TARGET]), float(df[HIGH_TARGET].mean()))
    return {"correct": clean, "leaked": leaked}


def body_length_pair(df: pd.DataFrame) -> dict[str, float]:
    """投稿後にしか分からない `body_length` を、入れた場合と外した場合で比べる。"""
    return {
        "correct": holdout_auc(df, numeric=BEFORE_POSTING),  # 投稿前に分かる 3 列 + category
        "leaked": holdout_auc(df),                           # body_length を入れた 4 列 + category
        "corr": float(df["body_length"].corr(df[REG_TARGET])),
    }


@lru_cache(maxsize=None)
def leak_experiments() -> list[dict]:
    """4 つの実験を「正しい手順」と「リークする手順」の対で並べる。"""
    df = load_review_table()
    scaler = scaler_leak_pair(df)
    noise = noise_leak_pair(df)
    target = target_encoding_pair(df)
    body = body_length_pair(df)
    rows = [
        {"label": "① 標準化を分割前に当てる", "kind": "前処理", **scaler},
        {"label": "② 雑音 500 列から分割前に選抜", "kind": "特徴量選択", **noise},
        {"label": "③ book_id の対応表を全データで作る", "kind": "エンコーディング", **target},
        {"label": "④ body_length（投稿後に決まる）を使う", "kind": "未来情報", **body},
    ]
    for row in rows:
        row["gap"] = row["leaked"] - row["correct"]
        row["fooled"] = bool(row["gap"] > TOLERANCE)
    return rows


# ==================================================================
# 解釈（セッション26）
# ==================================================================
def add_random_id(df: pd.DataFrame) -> pd.DataFrame:
    """0〜9,999 の意味のない整数列を足す。**分割の前に一度だけ**振る。"""
    rng = np.random.default_rng(RANDOM_STATE)
    return df.assign(**{RANDOM_ID: rng.integers(0, RANDOM_ID_MAX, len(df))})


@lru_cache(maxsize=None)
def gbm_bundle(with_random_id: bool = False) -> dict:
    """高評価分類の LightGBM を学習して、重要度を覗くための道具をまとめて返す。"""
    df = load_review_table()
    numeric = list(HIGH_NUMERIC)
    if with_random_id:
        df = add_random_id(df)
        numeric = numeric + [RANDOM_ID]
    features = numeric + HIGH_CATEGORICAL
    X_train, X_test, y_train, y_test = split_stratified(df[features], df[HIGH_TARGET])
    model = Pipeline([("pre", build_preprocess(numeric, HIGH_CATEGORICAL)), ("model", build_gbm())]).fit(
        X_train, y_train
    )
    return {
        "df": df,
        "features": features,
        "numeric": numeric,
        "X_train": X_train,
        "X_test": X_test,
        "y_train": y_train,
        "y_test": y_test,
        "pipeline": model,
        "names": clean_names(model.named_steps["pre"]),
        "roc_auc": float(roc_auc_score(y_test, positive_proba(model, X_test))),
    }


def impurity_table(with_random_id: bool = False) -> pd.DataFrame:
    """不純度ベースの重要度を 2 通り（split ＝ 使われた回数 / gain ＝ 減った不純度）並べる。"""
    bundle = gbm_bundle(with_random_id)
    booster = bundle["pipeline"].named_steps["model"].booster_
    table = pd.DataFrame(
        {
            "feature": bundle["names"],
            "split": booster.feature_importance(importance_type="split"),
            "gain": booster.feature_importance(importance_type="gain"),
        }
    )
    table["split_rank"] = table["split"].rank(ascending=False, method="min").astype("int64")
    table["gain_rank"] = table["gain"].rank(ascending=False, method="min").astype("int64")
    return table


@lru_cache(maxsize=None)
def permutation_table(which: str = "test", with_random_id: bool = False) -> pd.DataFrame:
    """permutation importance を大きい順に並べる（`which="test"` なら評価データで測る）。"""
    bundle = gbm_bundle(with_random_id)
    X = bundle["X_test"] if which == "test" else bundle["X_train"]
    y = bundle["y_test"] if which == "test" else bundle["y_train"]
    result = permutation_importance(
        bundle["pipeline"], X, y, scoring=SCORING, n_repeats=N_REPEATS, random_state=RANDOM_STATE
    )
    table = pd.DataFrame(
        {"feature": bundle["features"], "mean": result.importances_mean, "std": result.importances_std}
    )
    return table.sort_values("mean", ascending=False).reset_index(drop=True)


def permutation_value(feature: str, which: str = "test", with_random_id: bool = False) -> float:
    """列名を指定して permutation importance の値だけを取り出す。"""
    table = permutation_table(which, with_random_id)
    return float(table.loc[table["feature"] == feature, "mean"].iloc[0])


@lru_cache(maxsize=None)
def shap_bundle() -> dict:
    """SHAP の計算（数値 4 列・木 50 本・先頭 100 行）。警告は隠さず捕まえて返す。"""
    df = load_review_table()
    frame = df[HIGH_NUMERIC]  # One-Hot も標準化もせず、そのまま木に渡す
    model = lgb.LGBMClassifier(
        n_estimators=SHAP_N_ESTIMATORS, random_state=RANDOM_STATE, verbose=-1
    ).fit(frame, df[HIGH_TARGET])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")  # filterwarnings("ignore") で消してはいけない
        explainer = shap.TreeExplainer(model)
        values = np.asarray(explainer.shap_values(frame.head(SHAP_ROWS)))
    return {
        "model": model,
        "frame": frame,
        "values": values,
        "base": float(explainer.expected_value),
        "warnings": [w.category.__name__ for w in caught if "TreeExplainer" in str(w.message)],
    }


def sigmoid(x: float) -> float:
    """対数オッズを 0〜1 の確率に変換する（セッション17 と同じ）。"""
    return float(1.0 / (1.0 + np.exp(-x)))


def shap_mean_abs() -> pd.DataFrame:
    """SHAP 値の平均絶対値（全体としてどの列が効いたか）。"""
    bundle = shap_bundle()
    table = pd.DataFrame({"feature": HIGH_NUMERIC, "mean_abs": np.abs(bundle["values"]).mean(axis=0)})
    return table.sort_values("mean_abs", ascending=False).reset_index(drop=True)


def shap_local_check(row: int = 0) -> dict:
    """加法性（SHAP 値の合計 + 基準値 = 予測の対数オッズ）が成り立つことを確かめる。"""
    bundle = shap_bundle()
    total = float(bundle["values"][row].sum())
    logit = total + bundle["base"]
    from_model = float(bundle["model"].predict_proba(bundle["frame"].iloc[[row]])[0, 1])
    return {
        "values": dict(zip(HIGH_NUMERIC, (float(v) for v in bundle["values"][row]))),
        "total": total,
        "base": bundle["base"],
        "logit": logit,
        "proba_from_shap": sigmoid(logit),
        "proba_from_model": from_model,
        "matches": bool(abs(sigmoid(logit) - from_model) < 1e-6),
    }


def pdp_table(feature: str) -> pd.DataFrame:
    """1 つの列だけを動かしたときの「予測確率の平均」（訓練データの上で平均する）。"""
    bundle = gbm_bundle()
    X = bundle["X_train"].astype({name: "float64" for name in bundle["numeric"]})  # int は受け付けない
    result = partial_dependence(bundle["pipeline"], X, [feature], grid_resolution=GRID_RESOLUTION)
    return pd.DataFrame({"grid": result["grid_values"][0], "average": result["average"][0]})


# ==================================================================
# 監視（セッション28）
# ==================================================================
@lru_cache(maxsize=None)
def halves() -> dict:
    """注文を「前半（〜2025-08）」と「後半（2025-09〜）」に分ける（分布の比較は有効注文で）。"""
    orders = load_orders()
    before_all = orders.loc[orders["ordered_at"] < SPLIT_DATE]
    after_all = orders.loc[orders["ordered_at"] >= SPLIT_DATE]
    return {
        "before": before_all.loc[before_all["is_canceled"] == 0],
        "after": after_all.loc[after_all["is_canceled"] == 0],
    }


def psi_edges(expected, bins: int = PSI_BINS) -> np.ndarray:
    """学習したころのデータの分位からビン境界を作り、両端を開く（重なった境界は 1 本にする）。"""
    quantiles = np.quantile(np.asarray(expected, dtype="float64"), np.linspace(0.0, 1.0, bins + 1))
    edges = np.unique(quantiles)
    edges[0] = -np.inf
    edges[-1] = np.inf
    return edges


def bin_shares(values, edges: np.ndarray) -> np.ndarray:
    """各ビンに入った件数の比率（0 のビンは PSI_FLOOR でクリップする）。"""
    counts, _ = np.histogram(np.asarray(values, dtype="float64"), bins=edges)
    return np.clip(counts / counts.sum(), PSI_FLOOR, None)


def psi(expected, actual, bins: int = PSI_BINS) -> float:
    """PSI（Population Stability Index）。Σ(いま − 前) × log(いま / 前)。0 に近いほど動いていない。"""
    edges = psi_edges(expected, bins)
    expected_shares = bin_shares(expected, edges)
    actual_shares = bin_shares(actual, edges)
    return float(np.sum((actual_shares - expected_shares) * np.log(actual_shares / expected_shares)))


def verdict(value: float) -> str:
    """PSI の慣例的な目安で判定する（0.1 未満 / 0.1〜0.25 / 0.25 以上）。"""
    if value >= PSI_ACT:
        return "要再学習"
    if value >= PSI_WATCH:
        return "注意"
    return "安定"


def psi_table() -> pd.DataFrame:
    """監視したい 4 列をまとめて PSI にする（前半・後半の平均も並べる）。"""
    parts = halves()
    rows = []
    for column in PSI_COLUMNS:
        value = psi(parts["before"][column], parts["after"][column])
        rows.append(
            {
                "column": column,
                "psi": value,
                "judgement": verdict(value),
                "before_mean": float(parts["before"][column].mean()),
                "after_mean": float(parts["after"][column].mean()),
            }
        )
    return pd.DataFrame(rows)


def unit_price_drift() -> pd.DataFrame:
    """後半の単価を一律で何倍かにして、PSI がどこまで上がるかを並べる（監視の動作確認）。"""
    parts = halves()
    rows = []
    for ratio in DRIFT_RATIOS:
        value = psi(parts["before"]["unit_price"], parts["after"]["unit_price"] * ratio)
        rows.append({"ratio": float(ratio), "psi": value, "judgement": verdict(value)})
    return pd.DataFrame(rows)


def quantity_drift() -> dict:
    """後半の 30% の注文の数量を 5 に差し替えたときの PSI（差し替え前と後）。"""
    parts = halves()
    after = parts["after"]
    picked = after.sample(frac=QUANTITY_FRACTION, random_state=RANDOM_STATE).index
    changed = after.copy()
    changed.loc[picked, "quantity"] = QUANTITY_VALUE
    plain = psi(parts["before"]["quantity"], after["quantity"])
    injected = psi(parts["before"]["quantity"], changed["quantity"])
    return {
        "n_changed": int(round(len(after) * QUANTITY_FRACTION)),
        "psi_plain": plain,
        "psi_injected": injected,
        "judgement_injected": verdict(injected),
    }


def build_cancel_pipeline(class_weight: str | None = None) -> Pipeline:
    """セッション24 と同じ前処理 + LightGBM（比べるので条件を変えない）。"""
    return Pipeline(
        [
            ("pre", build_preprocess(CANCEL_NUMERIC, CANCEL_CATEGORICAL)),
            ("model", build_gbm(class_weight=class_weight)),
        ]
    )


def undersample(X_train: pd.DataFrame, y_train: pd.Series, ratio: float = 1.0):
    """訓練データの負例を捨てて、正例 : 負例 = 1 : ratio にそろえる（セッション24）。

    **評価データには絶対に当てません。** 当てると指標が本番の見積もりでなくなります。
    """
    train = pd.concat([X_train, y_train], axis=1)
    positives = train.loc[train["is_canceled"] == POSITIVE_LABEL]
    negatives = train.loc[train["is_canceled"] == NEGATIVE_LABEL]
    kept = negatives.sample(n=int(round(len(positives) * ratio)), random_state=RANDOM_STATE)
    resampled = pd.concat([positives, kept]).sample(frac=1, random_state=RANDOM_STATE)
    return resampled[CANCEL_FEATURES], resampled["is_canceled"]


@lru_cache(maxsize=None)
def cancel_bundle(kind: str = "plain") -> dict:
    """キャンセル予測（無作為分割）。kind は "plain" / "balanced" / "under"。"""
    if kind not in CANCEL_KINDS:
        raise ValueError(f"kind は {CANCEL_KINDS} のいずれかにしてください: {kind}")
    df = load_cancel_table()
    X_train, X_test, y_train, y_test = split_stratified(df[CANCEL_FEATURES], df["is_canceled"])
    if kind == "under":
        X_fit, y_fit = undersample(X_train, y_train)
        weight = None
    else:
        X_fit, y_fit = X_train, y_train
        weight = "balanced" if kind == "balanced" else None
    model = build_cancel_pipeline(weight).fit(X_fit, y_fit)
    return {
        "n_rows": int(len(df)),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "n_fit": int(len(X_fit)),
        "y_test": y_test,
        "proba": positive_proba(model, X_test),
    }


@lru_cache(maxsize=None)
def cancel_time_split() -> dict:
    """前半で学習し、後半で評価する（本番の順序と同じ向きに時間で分ける）。"""
    df = load_cancel_table()
    train = df.loc[df["ordered_at"] < SPLIT_DATE]
    test = df.loc[df["ordered_at"] >= SPLIT_DATE]
    model = build_cancel_pipeline().fit(train[CANCEL_FEATURES], train["is_canceled"])
    proba = positive_proba(model, test[CANCEL_FEATURES])
    return {
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "train_end": train["ordered_at"].max(),
        "y_test": test["is_canceled"].to_numpy(),
        "proba": proba,
        "month": test["ordered_at"].dt.to_period("M").astype("str").to_numpy(),
        "roc_auc": float(roc_auc_score(test["is_canceled"], proba)),
        "pr_auc": float(average_precision_score(test["is_canceled"], proba)),
    }


def monthly_auc(months: int = MONITOR_MONTHS) -> pd.DataFrame:
    """月ごとの ROC AUC を並べ、直近 months か月ぶんを返す（片方のクラスしかない月は飛ばす）。"""
    bundle = cancel_time_split()
    frame = pd.DataFrame({"month": bundle["month"], "y": bundle["y_test"], "proba": bundle["proba"]})
    rows = []
    for month, part in frame.groupby("month", sort=True):
        if part["y"].nunique() < 2:
            continue
        rows.append({"month": str(month), "roc_auc": float(roc_auc_score(part["y"], part["proba"]))})
    return pd.DataFrame(rows).tail(months).reset_index(drop=True)


def trend_summary(table: pd.DataFrame | None = None) -> dict:
    """月次の AUC に「下降トレンドがあるか」を決まった手続きで判定する。

    1 か月下がっただけでは判断しません。① 直近が平均 − 2σ を下回るか、
    ② 2 か月続けて下回るか、③ 傾きが SLOPE_LIMIT より急か、を順に見ます。
    """
    table = monthly_auc() if table is None else table
    values = table["roc_auc"].to_numpy(dtype="float64")
    mean = float(values.mean())
    std = float(values.std())  # ddof=0。この 6 か月そのもののばらつき
    lower = mean - BAND_SIGMA * std
    below = values < lower
    slope = float(np.polyfit(np.arange(len(values), dtype="float64"), values, 1)[0])
    consecutive = bool(np.any(below[1:] & below[:-1]))
    return {
        "months": [str(m) for m in table["month"]],
        "values": [float(v) for v in values],
        "mean": mean,
        "std": std,
        "lower": lower,
        "upper": mean + BAND_SIGMA * std,
        "span": float(values.max() - values.min()),
        "latest": float(values[-1]),
        "n_below": int(below.sum()),
        "consecutive_below": consecutive,
        "slope": slope,
        "declining": bool(below[-1] and consecutive) or bool(slope < SLOPE_LIMIT),
    }


def retrain_rules() -> list[dict]:
    """再学習するかどうかを 4 つの条件で機械的に判定する（先に条件と閾値を書いておく）。"""
    drift = psi_table()
    psi_max = float(drift["psi"].max())
    psi_worst = str(drift.loc[drift["psi"].idxmax(), "column"])
    trend = trend_summary()
    split = cancel_time_split()
    elapsed_days = int((AS_OF - split["train_end"]).days)
    growth = len(load_orders()) / split["n_train"]
    return [
        {
            "name": "データドリフト",
            "rule": f"PSI の最大が {PSI_ACT} 以上",
            "actual": f"{psi_max:.4f}（{psi_worst}）",
            "fire": bool(psi_max >= PSI_ACT),
        },
        {
            "name": "性能の低下",
            "rule": f"月次 AUC が「平均 − {BAND_SIGMA:.0f}σ」を 2 か月連続で下回る",
            "actual": f"下回った月 {trend['n_below']} か月（連続は{'あり' if trend['consecutive_below'] else 'なし'}）",
            "fire": bool(trend["declining"]),
        },
        {
            "name": "時間の経過",
            "rule": f"学習データの最終日から {RETRAIN_MAX_DAYS} 日以上",
            "actual": f"{elapsed_days:,} 日",
            "fire": bool(elapsed_days >= RETRAIN_MAX_DAYS),
        },
        {
            "name": "データ量の増加",
            "rule": f"学習時の {RETRAIN_GROWTH:.1f} 倍以上",
            "actual": f"{growth:.2f} 倍",
            "fire": bool(growth >= RETRAIN_GROWTH),
        },
    ]


def should_retrain(rules: list[dict] | None = None) -> dict:
    """1 つでも条件が発火したら再学習する、という方針にする。"""
    rules = retrain_rules() if rules is None else rules
    fired = [str(rule["name"]) for rule in rules if rule["fire"]]
    return {"retrain": bool(fired), "fired": fired, "n_fired": len(fired), "n_rules": len(rules)}


# ==================================================================
# 図
# ==================================================================
def save_fig(fig: Figure, name: str) -> str:
    """図を outputs/ に保存し、Figure を閉じてファイル名を返す（`plt.show()` は使わない）。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT_DIR / name, dpi=110)
    plt.close(fig)  # 閉じないと Figure が開いたまま溜まっていく
    return name
