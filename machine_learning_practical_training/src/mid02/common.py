"""中間プロジェクト②で共通して使う読み込み・モデル・指標（配布コード）。

同じディレクトリのスクリプトから次のように使います。

    from common import cancel_probabilities, report_card, threshold_table

    y_test, proba = cancel_probabilities()   # 基準モデルの予測確率
    rows = threshold_table(y_test, proba)    # 閾値 4 段階の指標

キャンセル予測の作り方は src/verify_setup.py の 6 節・セッション14・セッション24 と
まったく同じです（orders.drop_duplicates("order_id") に customers を結合して
days_since_signup を作る）。**行を並べ替えません。** sort_values を挟むと同じ
random_state でも別の分割になり、ROC AUC が 0.7911 から変わります（本書の規約）。

前処理は Pipeline ではなく ColumnTransformer を手で fit / transform します
（Pipeline への組み替えは「セッション25：Pipeline と ColumnTransformer」で扱います）。
同じプロセスの中では学習結果を使い回します（_CACHE）。1 回の学習に数秒かかるため、
report.py のように何度も呼ぶスクリプトでは効果が大きくなります。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 画面のないコンテナで図を PNG として保存するための設定
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.compose import ColumnTransformer
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# 分割と学習の条件は全章で共通（本書の規約）
TEST_SIZE = 0.25
RANDOM_STATE = 42
N_ESTIMATORS = 200
N_SPLITS = 5

# 基準モデルの特徴量（セッション14 の増分実験②と同じ 5 列）
NUMERIC = ["unit_price", "quantity", "discount_rate", "days_since_signup"]
CATEGORICAL = ["channel"]
FEATURES = NUMERIC + CATEGORICAL

# 陽性（1）は「キャンセルされる」、陰性（0）は「キャンセルされない」
POSITIVE_LABEL = 1
NEGATIVE_LABEL = 0

# 確率をクラスに変えるときの境目。0.5 は「既定値」であって「正解」ではない（セッション20）
DEFAULT_THRESHOLD = 0.5
# 報告に使う閾値。不均衡データでは 0.5 より下を見ることになる
THRESHOLDS = [0.1, 0.2, 0.3, 0.5]
# 図を描くときだけ使う細かい刻み（0.05 から 0.95 まで）
THRESHOLD_GRID = np.round(np.arange(0.05, 1.00, 0.05), 2)

# 運用の前提。評価データ 15,008 件を「これから 1 か月に入る注文」と見なして、
# 確認の連絡を入れられる件数の上限を決める（この 4 行が閾値の根拠になる）
OPERATORS = 1          # 対応する人数
CALLS_PER_DAY = 20     # 1 人が 1 日に入れられる確認の連絡
BUSINESS_DAYS = 20     # 1 か月の営業日
MONTHLY_CAPACITY = OPERATORS * CALLS_PER_DAY * BUSINESS_DAYS  # 月 400 件まで

# ID は数値に見えても文字列として読む（先頭の 0 が落ちないようにする）
ID_COLUMNS = {"order_id": "str", "customer_id": "str", "book_id": "str"}

# 比べる 3 つの学習のしかた（セッション24 と同じ）
MODEL_KINDS = ("plain", "balanced", "under")
KIND_NAMES = {
    "plain": "重みなし",
    "balanced": 'class_weight="balanced"',
    "under": "1:1 アンダーサンプリング",
}

# 同じプロセスの中で同じ学習を繰り返さないための入れ物
_CACHE: dict[tuple, object] = {}


@lru_cache(maxsize=1)
def load_order_table() -> pd.DataFrame:
    """キャンセル予測の土台になる表を作る（60,031 行・並び順は merge した直後のまま）。

    返り値は使い回されます。列を足すときは add_* 関数のように copy() を取ってください。
    """
    orders = pd.read_csv(DATA_DIR / "orders.csv", dtype=ID_COLUMNS, parse_dates=["ordered_at"])
    customers = pd.read_csv(
        DATA_DIR / "customers.csv",
        dtype={"customer_id": "str"},
        parse_dates=["signup_date"],
    )
    df = orders.drop_duplicates("order_id").merge(  # 重複 30 件を落とす（セッション04）
        customers[["customer_id", "channel", "signup_date", "birth_year"]],
        on="customer_id",
        how="left",
    )
    df["days_since_signup"] = (df["ordered_at"] - df["signup_date"]).dt.days
    return df


def split_xy(df: pd.DataFrame, numeric: list[str] | None = None, categorical: list[str] | None = None):
    """特徴量と目的変数を切り出して訓練・評価に分ける（条件は全章共通）。"""
    numeric = NUMERIC if numeric is None else numeric
    categorical = CATEGORICAL if categorical is None else categorical
    X = df[numeric + categorical]
    y = df["is_canceled"]
    return train_test_split(X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)


def make_preprocess(numeric: list[str] | None = None, categorical: list[str] | None = None) -> ColumnTransformer:
    """数値列を標準化し、カテゴリ列を 0/1 に開く前処理（引数は常に明示する）。"""
    numeric = NUMERIC if numeric is None else numeric
    categorical = CATEGORICAL if categorical is None else categorical
    transformers: list[tuple] = [("num", StandardScaler(), numeric)]
    if categorical:
        # handle_unknown・sparse_output はバージョンで既定値が変わるので必ず書く
        transformers.append(("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical))
    return ColumnTransformer(transformers)


def fit_predict_proba(
    X_train,
    y_train,
    X_test,
    numeric: list[str] | None = None,
    categorical: list[str] | None = None,
    class_weight: str | None = None,
) -> np.ndarray:
    """前処理を訓練データだけで fit し、評価データが陽性である予測確率を返す。

    fit_transform を当てるのは訓練データだけです。評価データに fit_transform を
    当てると、評価データの平均と分散が学習に混ざります（セッション22 のリーク）。
    """
    pre = make_preprocess(numeric, categorical)
    X_train_t = pre.fit_transform(X_train)  # 訓練データだけで平均と分散を決める
    X_test_t = pre.transform(X_test)        # 評価データは transform だけ
    model = LGBMClassifier(
        n_estimators=N_ESTIMATORS,
        random_state=RANDOM_STATE,
        verbose=-1,
        class_weight=class_weight,
    )
    model.fit(X_train_t, y_train)
    return model.predict_proba(X_test_t)[:, 1]


def undersample(X_train: pd.DataFrame, y_train: pd.Series, ratio: float = 1.0):
    """訓練データの負例を捨てて、正例 : 負例 = 1 : ratio にそろえる（セッション24）。

    **評価データには絶対に当てません。** 当てると指標が本番の見積もりでなくなります。
    """
    train = pd.concat([X_train, y_train], axis=1)
    positives = train.loc[train["is_canceled"] == POSITIVE_LABEL]
    negatives = train.loc[train["is_canceled"] == NEGATIVE_LABEL]
    kept = negatives.sample(n=int(round(len(positives) * ratio)), random_state=RANDOM_STATE)
    resampled = pd.concat([positives, kept]).sample(frac=1, random_state=RANDOM_STATE)
    return resampled[FEATURES], resampled["is_canceled"]


def cancel_probabilities(kind: str = "plain"):
    """(評価データの正解, 予測確率) を返す。kind は MODEL_KINDS のいずれか。"""
    if kind not in MODEL_KINDS:
        raise ValueError(f"kind は {MODEL_KINDS} のいずれかにしてください: {kind}")
    key = ("proba", kind)
    if key in _CACHE:
        return _CACHE[key]

    X_train, X_test, y_train, y_test = split_xy(load_order_table())
    if kind == "under":
        X_fit, y_fit = undersample(X_train, y_train)
        class_weight = None
    else:
        X_fit, y_fit = X_train, y_train
        class_weight = "balanced" if kind == "balanced" else None

    proba = fit_predict_proba(X_fit, y_fit, X_test, class_weight=class_weight)
    _CACHE[key] = (y_test, proba)
    return _CACHE[key]


def describe_split(df: pd.DataFrame) -> dict[str, float]:
    """母集団・訓練・評価の件数と正例率（不均衡の度合いを最初に確認する）。"""
    X_train, X_test, y_train, y_test = split_xy(df)
    return {
        "n_rows": len(df),
        "n_positive": int(df["is_canceled"].sum()),
        "n_train": len(X_train),
        "n_test": len(X_test),
        "n_train_positive": int(y_train.sum()),
        "n_train_negative": int(len(y_train) - y_train.sum()),
        "n_test_positive": int(y_test.sum()),
        "rate_all": float(df["is_canceled"].mean()),
        "rate_train": float(y_train.mean()),
        "rate_test": float(y_test.mean()),
    }


def predict_at(proba, threshold: float = DEFAULT_THRESHOLD) -> np.ndarray:
    """確率を閾値で切ってクラス（0 / 1）に変える。predict は threshold=0.5 と同じ。"""
    return (np.asarray(proba) >= threshold).astype("int64")


def confusion_parts(y_true, y_pred) -> dict[str, int]:
    """混同行列の 4 象限を名前付きで取り出す（labels を明示して並びを固定する）。"""
    matrix = confusion_matrix(y_true, y_pred, labels=[NEGATIVE_LABEL, POSITIVE_LABEL])
    tn, fp, fn, tp = matrix.ravel()
    return {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}


def print_confusion(parts: dict[str, int]) -> None:
    """混同行列を 4 象限の呼び名つきで表示する。"""
    print("                予測: しない   予測: する")
    print(f"実測: しない   TN {parts['tn']:>8,}   FP {parts['fp']:>6,}")
    print(f"実測: する     FN {parts['fn']:>8,}   TP {parts['tp']:>6,}")


def score_summary(y_true, proba, threshold: float = DEFAULT_THRESHOLD) -> dict[str, float]:
    """報告に使う指標をまとめて計算する。

    accuracy も計算しますが、これは「ベースラインと同じ値になる」ことを示すためだけに
    使います（報告カードには載せません）。
    """
    y_pred = predict_at(proba, threshold)
    return {
        "roc_auc": float(roc_auc_score(y_true, proba)),
        "pr_auc": float(average_precision_score(y_true, proba)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "mean_proba": float(np.mean(np.asarray(proba))),
        "brier": float(brier_score_loss(y_true, proba)),
    }


def baseline_scores(y_true) -> dict[str, float]:
    """「全部キャンセルされない」と答えるだけのベースライン（多数クラス予測）。"""
    y_array = np.asarray(y_true)
    always_zero = np.zeros(len(y_array), dtype="int64")
    constant = np.full(len(y_array), float(y_array.mean()))  # 全件同じ確率なので順位が付かない
    return {
        "accuracy": float(accuracy_score(y_array, always_zero)),
        "roc_auc": float(roc_auc_score(y_array, constant)),
        "pr_auc": float(average_precision_score(y_array, constant)),
        "positive_rate": float(y_array.mean()),
        "n_positive": int(y_array.sum()),
        "n_rows": int(len(y_array)),
    }


def threshold_metrics(y_true, proba, threshold: float) -> dict[str, float]:
    """閾値 1 つぶんの指標。件数（陽性・捕まえた・見逃した・空振り）も一緒に返す。"""
    y_pred = predict_at(proba, threshold)
    parts = confusion_parts(y_true, y_pred)
    precision = float(precision_score(y_true, y_pred, zero_division=0))
    return {
        "threshold": float(threshold),
        "n_positive": parts["fp"] + parts["tp"],
        "tp": parts["tp"],
        "fn": parts["fn"],
        "fp": parts["fp"],
        "precision": precision,
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        # 1 件のキャンセルを捕まえるのに何件の連絡が必要か（適合率の逆数）
        "calls_per_catch": float("inf") if precision == 0 else 1.0 / precision,
    }


def threshold_table(y_true, proba, thresholds=None) -> list[dict[str, float]]:
    """複数の閾値について threshold_metrics を並べる。"""
    targets = THRESHOLDS if thresholds is None else thresholds
    return [threshold_metrics(y_true, proba, float(t)) for t in targets]


def format_calls(calls: float) -> str:
    """「1 件捕まえるのに必要な連絡」の表示。陽性が 0 件のときは — にする。"""
    return "—" if not np.isfinite(calls) else f"{calls:.1f} 件"


def print_threshold_table(rows: list[dict[str, float]]) -> None:
    """閾値の表を 1 行 1 閾値で表示する。"""
    print("閾値 | 適合率 | 再現率 |   F1   | 陽性と予測 | 捕まえた | 見逃した | 1 件捕まえるのに必要な連絡")
    for row in rows:
        print(
            f"{row['threshold']:.1f}  | {row['precision']:.4f} | {row['recall']:.4f} |"
            f" {row['f1']:.4f} | {row['n_positive']:>6,} 件 | {row['tp']:>5,} 件 |"
            f" {row['fn']:>5,} 件 | {format_calls(row['calls_per_catch'])}"
        )


def choose_threshold(y_true, proba, capacity: int = MONTHLY_CAPACITY, thresholds=None) -> dict[str, float]:
    """対応できる件数に収まる閾値のうち、再現率がいちばん高いものを選ぶ。

    「F1 がいちばん高い閾値」ではなく「業務が回る範囲でいちばん多く捕まえられる閾値」
    を選ぶのが本プロジェクトの決め方です。
    """
    rows = threshold_table(y_true, proba, thresholds)
    affordable = [row for row in rows if row["n_positive"] <= capacity]
    if not affordable:
        raise ValueError(f"どの閾値でも {capacity:,} 件を超えます。閾値の候補か対応件数を見直してください。")
    return max(affordable, key=lambda row: (row["recall"], -row["threshold"]))


def report_card(y_true, proba, threshold: float, capacity: int = MONTHLY_CAPACITY) -> dict[str, float]:
    """不均衡データで報告すべき指標のセット（accuracy を報告項目に入れない）。"""
    row = threshold_metrics(y_true, proba, threshold)
    scores = score_summary(y_true, proba)
    base = baseline_scores(y_true)
    return {
        "n_rows": base["n_rows"],
        "n_positive": base["n_positive"],
        "positive_rate": base["positive_rate"],
        "pr_auc": scores["pr_auc"],
        "pr_lift": scores["pr_auc"] / base["positive_rate"],
        "roc_auc": scores["roc_auc"],
        "threshold": row["threshold"],
        "precision": row["precision"],
        "recall": row["recall"],
        "calls_per_catch": row["calls_per_catch"],
        "n_predicted_positive": row["n_positive"],
        "tp": row["tp"],
        "fn": row["fn"],
        "fp": row["fp"],
        "capacity": capacity,
        "headroom": capacity - row["n_positive"],
        "brier": scores["brier"],
        "mean_proba": scores["mean_proba"],
        # 報告しない値。「ベースラインと同じ」ことを示すためだけに残す
        "accuracy_not_reported": scores["accuracy"],
    }


def print_report_card(card: dict[str, float], title: str) -> None:
    """報告カードを決まった順に表示する（毎回同じ順で出すことが大事）。"""
    print(f"■ 不均衡データの報告カード（{title}）")
    print("予測タスク          : 注文がキャンセルされるかどうか（陽性 = キャンセル）")
    print(f"評価データ          : {card['n_rows']:,} 件・正例 {card['n_positive']:,} 件"
          f"（正例率 {card['positive_rate']:.4f}）")
    print(f"PR-AUC              : {card['pr_auc']:.4f}"
          f"（ベースライン {card['positive_rate']:.4f} の {card['pr_lift']:.1f} 倍）")
    print(f"ROC AUC             : {card['roc_auc']:.4f}（参考。不均衡では楽観的に見える）")
    print(f"運用する閾値        : {card['threshold']:.1f}"
          f"（月 {card['capacity']:,} 件の連絡枠に収まる中で再現率が最大）")
    print(f"  適合率            : {card['precision']:.4f}"
          f"（連絡 {format_calls(card['calls_per_catch'])}で 1 件が当たり）")
    print(f"  再現率            : {card['recall']:.4f}")
    print(f"  陽性と予測        : {card['n_predicted_positive']:,} 件"
          f"（枠 {card['capacity']:,} 件に対して {card['headroom']:,} 件の余裕）")
    print(f"  捕まえた / 見逃した / 空振り: {card['tp']:,} / {card['fn']:,} / {card['fp']:,} 件")
    print(f"Brier スコア        : {card['brier']:.5f}")
    print(f"予測確率の平均      : {card['mean_proba']:.4f}（実際の正例率 {card['positive_rate']:.4f}）")
    print("※ accuracy は載せない（全部「キャンセルされない」と答えても同じ値になるため）")


def cross_validate_folds(
    df: pd.DataFrame,
    numeric: list[str] | None = None,
    categorical: list[str] | None = None,
    n_splits: int = N_SPLITS,
) -> list[dict[str, float]]:
    """層化 K 分割の交差検証。fold ごとに前処理を fit し直して指標を測る。

    ホールドアウト 1 回の見積もりが偶然ではないかを確かめるために使います
    （交差検証そのものは「セッション22：交差検証とデータリーク」で扱いました）。
    """
    numeric = NUMERIC if numeric is None else numeric
    categorical = CATEGORICAL if categorical is None else categorical
    key = ("cv", tuple(numeric), tuple(categorical), n_splits)
    if key in _CACHE:
        return _CACHE[key]

    X = df[numeric + categorical]
    y = df["is_canceled"]
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=RANDOM_STATE)
    rows: list[dict[str, float]] = []
    for fold, (train_index, valid_index) in enumerate(cv.split(X, y), start=1):
        X_tr, X_va = X.iloc[train_index], X.iloc[valid_index]
        y_tr, y_va = y.iloc[train_index], y.iloc[valid_index]
        proba = fit_predict_proba(X_tr, y_tr, X_va, numeric, categorical)
        rows.append(
            {
                "fold": fold,
                "positive_rate": float(y_va.mean()),
                "roc_auc": float(roc_auc_score(y_va, proba)),
                "pr_auc": float(average_precision_score(y_va, proba)),
            }
        )
    _CACHE[key] = rows
    return rows


def evaluate_features(df: pd.DataFrame, numeric: list[str], categorical: list[str]) -> dict[str, float]:
    """指定した特徴量で学習し、列数・ROC AUC・PR-AUC を返す（増分実験の 1 段階ぶん）。

    キャッシュの鍵は列の組み合わせだけです。渡す df は同じ表（add_all_features の
    返り値）であることを前提にしています。
    """
    key = ("step", tuple(numeric), tuple(categorical))
    if key in _CACHE:
        return dict(_CACHE[key])

    X_train, X_test, y_train, y_test = split_xy(df, numeric, categorical)
    proba = fit_predict_proba(X_train, y_train, X_test, numeric, categorical)
    result = {
        "n_features": len(numeric) + len(categorical),
        "roc_auc": float(roc_auc_score(y_test, proba)),
        "pr_auc": float(average_precision_score(y_test, proba)),
    }
    _CACHE[key] = result
    return dict(result)


def pr_points(y_true, proba):
    """PR 曲線の点（適合率・再現率・閾値）。"""
    return precision_recall_curve(y_true, proba)


def save_figure(fig, name: str) -> Path:
    """図を outputs/ に保存してパスを返す（MPLBACKEND=Agg なので plt.show は使わない）。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)  # 閉じないと Figure が開いたまま溜まっていく
    return path
