"""セッション 24 の本文・練習問題・解答で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import cancel_probabilities, confusion_parts, predict_at

    y_test, proba = cancel_probabilities("plain")
    parts = confusion_parts(y_test, predict_at(proba, 0.5))

キャンセル予測の作り方は src/verify_setup.py の 6 節とまったく同じです
（orders.drop_duplicates("order_id") に customers を結合して days_since_signup を作る）。
**行を並べ替えません。** sort_values を挟むと同じ random_state でも別の分割になり、
ROC AUC が 0.7911 から変わります（本書の規約）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.calibration import calibration_curve
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
    roc_curve,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# 分割と学習の条件は全章で共通（本書の規約）
TEST_SIZE = 0.25
RANDOM_STATE = 42
N_ESTIMATORS = 200

# キャンセル予測の特徴量（セッション14 で積み上げたものと同じ）
NUMERIC = ["unit_price", "quantity", "discount_rate", "days_since_signup"]
CATEGORICAL = ["channel"]
FEATURES = NUMERIC + CATEGORICAL

# 陽性（1）は「キャンセルされる」、陰性（0）は「キャンセルされない」
POSITIVE_LABEL = 1
NEGATIVE_LABEL = 0

# 確率をクラスに変えるときの境目。0.5 は「既定値」であって「正解」ではない（セッション20）
DEFAULT_THRESHOLD = 0.5
# 本章で表にする閾値。不均衡データでは 0.5 より下を見ることになる
THRESHOLDS = [0.1, 0.2, 0.3, 0.5]
# 図を描くときだけ使う細かい刻み（0.05 から 0.95 まで）
THRESHOLD_GRID = np.round(np.arange(0.05, 1.00, 0.05), 2)

# キャリブレーション曲線の設定。件数をそろえた 5 分位で区切る
CALIBRATION_BINS = 5
CALIBRATION_STRATEGY = "quantile"

# ID は数値に見えても文字列として読む（先頭の 0 が落ちないようにする）
ID_COLUMNS = {"order_id": "str", "customer_id": "str", "book_id": "str"}

# 本章で比べる 3 つの学習のしかた
MODEL_KINDS = ("plain", "balanced", "under")
KIND_NAMES = {
    "plain": "重みなし",
    "balanced": "class_weight=balanced",
    "under": "1:1 アンダーサンプリング",
}

# 同じプロセスの中で同じモデルを何度も学習しないための入れ物
_PROBA_CACHE: dict[str, tuple] = {}


def load_cancel_table() -> pd.DataFrame:
    """キャンセル予測に使う表を作る（src/verify_setup.py の 6 節と同じ作り方・同じ並び）。

    重複 30 件を落とした 60,031 行に、顧客の流入経路と登録日を結合し、
    「登録から何日目の注文か」を作って返します。**行を並べ替えません。**
    """
    orders = pd.read_csv(DATA_DIR / "orders.csv", dtype=ID_COLUMNS, parse_dates=["ordered_at"])
    customers = pd.read_csv(
        DATA_DIR / "customers.csv",
        dtype={"customer_id": "str"},
        parse_dates=["signup_date"],
    )
    df = orders.drop_duplicates("order_id").merge(  # 重複 30 件を落とす（セッション04）
        customers[["customer_id", "channel", "signup_date"]], on="customer_id", how="left"
    )
    df["days_since_signup"] = (df["ordered_at"] - df["signup_date"]).dt.days
    return df


def split_xy(df: pd.DataFrame):
    """キャンセルするかどうかを目的変数にして訓練・評価に分ける（条件は全章共通）。"""
    X = df[FEATURES]
    y = df["is_canceled"]
    return train_test_split(X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)


def make_preprocess() -> ColumnTransformer:
    """数値 4 列を標準化し、channel を 0/1 の 4 列に開く（引数は常に明示する）。"""
    return ColumnTransformer(
        [
            ("num", StandardScaler(), NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
        ]
    )


def make_pipeline(class_weight: str | None = None) -> Pipeline:
    """前処理 + LightGBM。class_weight="balanced" にすると少数クラスを重く扱う。"""
    return Pipeline(
        [
            ("pre", make_preprocess()),
            (
                "model",
                LGBMClassifier(
                    n_estimators=N_ESTIMATORS,
                    random_state=RANDOM_STATE,
                    verbose=-1,
                    class_weight=class_weight,
                ),
            ),
        ]
    )


def fit_proba(X_fit, y_fit, X_test, class_weight: str | None = None):
    """学習して、評価データが陽性である予測確率を返す。"""
    pipeline = make_pipeline(class_weight).fit(X_fit, y_fit)
    return pipeline.predict_proba(X_test)[:, 1]


def undersample(X_train: pd.DataFrame, y_train: pd.Series, ratio: float = 1.0):
    """訓練データの負例を捨てて、正例 : 負例 = 1 : ratio にそろえる。

    正例は全件残し、負例から同数（ratio 倍）を抽出してから全体をシャッフルします。
    **評価データには絶対に当てません。** 当てると指標が本番の見積もりでなくなります。
    """
    train = pd.concat([X_train, y_train], axis=1)
    positives = train.loc[train["is_canceled"] == POSITIVE_LABEL]
    negatives = train.loc[train["is_canceled"] == NEGATIVE_LABEL]
    kept = negatives.sample(n=int(round(len(positives) * ratio)), random_state=RANDOM_STATE)
    resampled = pd.concat([positives, kept]).sample(frac=1, random_state=RANDOM_STATE)
    return resampled[FEATURES], resampled["is_canceled"]


def cancel_probabilities(kind: str = "plain"):
    """(評価データの正解, 予測確率) を返す。kind は MODEL_KINDS のいずれか。

    同じプロセスの中では学習結果を使い回します（1 回の学習に数秒かかるため）。
    """
    if kind not in MODEL_KINDS:
        raise ValueError(f"kind は {MODEL_KINDS} のいずれかにしてください: {kind}")
    if kind in _PROBA_CACHE:
        return _PROBA_CACHE[kind]

    X_train, X_test, y_train, y_test = split_xy(load_cancel_table())
    if kind == "under":
        X_fit, y_fit = undersample(X_train, y_train)
        class_weight = None
    else:
        X_fit, y_fit = X_train, y_train
        class_weight = "balanced" if kind == "balanced" else None

    proba = fit_proba(X_fit, y_fit, X_test, class_weight)
    _PROBA_CACHE[kind] = (y_test, proba)
    return y_test, proba


def describe_split(df: pd.DataFrame) -> dict[str, object]:
    """母集団・訓練・評価の件数と正例率をまとめる（不均衡の度合いを最初に確認する）。"""
    X_train, X_test, y_train, y_test = split_xy(df)
    return {
        "n_rows": len(df),
        "n_train": len(X_train),
        "n_test": len(X_test),
        "n_train_positive": int(y_train.sum()),
        "n_test_positive": int(y_test.sum()),
        "n_train_negative": int(len(y_train) - y_train.sum()),
        "rate_all": float(df["is_canceled"].mean()),
        "rate_train": float(y_train.mean()),
        "rate_test": float(y_test.mean()),
    }


def predict_at(proba, threshold: float = DEFAULT_THRESHOLD):
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
    """不均衡データを語るのに必要な指標をまとめて計算する。

    accuracy も計算しますが、これは「ベースラインと同じ値になる」ことを示すためだけに使います。
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
    """閾値 1 つぶんの指標。捕まえた件数（TP）と見逃した件数（FN）も一緒に返す。"""
    parts = confusion_parts(y_true, predict_at(proba, threshold))
    y_pred = predict_at(proba, threshold)
    return {
        "threshold": float(threshold),
        "n_positive": parts["fp"] + parts["tp"],
        "tp": parts["tp"],
        "fn": parts["fn"],
        "fp": parts["fp"],
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
    }


def threshold_table(y_true, proba, thresholds=None) -> list[dict[str, float]]:
    """複数の閾値について threshold_metrics を並べる。"""
    targets = THRESHOLDS if thresholds is None else thresholds
    return [threshold_metrics(y_true, proba, t) for t in targets]


def print_threshold_table(rows: list[dict[str, float]]) -> None:
    """閾値の表を 1 行 1 閾値で表示する。"""
    print("閾値 | 適合率 | 再現率 |   F1   | 陽性と予測 | 捕まえた | 見逃した")
    for row in rows:
        print(
            f"{row['threshold']:.1f}  | {row['precision']:.4f} | {row['recall']:.4f} |"
            f" {row['f1']:.4f} | {row['n_positive']:>6,} 件 |"
            f" {row['tp']:>5,} 件 | {row['fn']:>5,} 件"
        )


def best_f1_row(rows: list[dict[str, float]]) -> dict[str, float]:
    """F1 がいちばん高い行を返す（同点なら閾値が小さいほうを選ぶ）。"""
    return max(rows, key=lambda row: (row["f1"], -row["threshold"]))


def calibration_points(y_true, proba):
    """キャリブレーション曲線の点を返す（予測の平均, 実際の割合）の順にそろえる。"""
    prob_true, prob_pred = calibration_curve(
        y_true, proba, n_bins=CALIBRATION_BINS, strategy=CALIBRATION_STRATEGY
    )
    return [float(v) for v in prob_pred], [float(v) for v in prob_true]


def calibration_gap(y_true, proba) -> float:
    """キャリブレーション曲線が対角線からいちばん離れている量。"""
    prob_pred, prob_true = calibration_points(y_true, proba)
    return max(abs(pred - true) for pred, true in zip(prob_pred, prob_true))


def print_calibration(prob_pred, prob_true) -> None:
    """キャリブレーション曲線を表として表示する。"""
    print("  予測の平均 | 実際の割合")
    for pred, true in zip(prob_pred, prob_true):
        print(f"     {pred:.4f} |    {true:.4f}")


def report_card(y_true, proba, threshold: float) -> dict[str, object]:
    """不均衡データで報告すべき指標のセット（accuracy を入れない）。"""
    row = threshold_metrics(y_true, proba, threshold)
    scores = score_summary(y_true, proba)
    base = baseline_scores(y_true)
    return {
        "positive_rate": base["positive_rate"],
        "n_positive": base["n_positive"],
        "n_rows": base["n_rows"],
        "pr_auc": scores["pr_auc"],
        "roc_auc": scores["roc_auc"],
        "threshold": row["threshold"],
        "precision": row["precision"],
        "recall": row["recall"],
        "n_predicted_positive": row["n_positive"],
        "tp": row["tp"],
        "fn": row["fn"],
        "fp": row["fp"],
        "brier": scores["brier"],
        "mean_proba": scores["mean_proba"],
        "accuracy_not_reported": scores["accuracy"],
    }


def print_report_card(card: dict[str, object], title: str) -> None:
    """報告カードを決まった順に表示する（毎回同じ順で出すことが大事）。"""
    print(f"■ 不均衡データの報告カード（{title}）")
    print(f"正例率（評価データ）: {card['positive_rate']:.4f}（{card['n_positive']:,} / {card['n_rows']:,} 件）")
    print(f"PR-AUC              : {card['pr_auc']:.4f}")
    print(f"ROC AUC             : {card['roc_auc']:.4f}（参考。不均衡では楽観的に見える）")
    print(f"運用する閾値        : {card['threshold']:.1f}")
    print(f"  適合率            : {card['precision']:.4f}")
    print(f"  再現率            : {card['recall']:.4f}")
    print(f"  陽性と予測        : {card['n_predicted_positive']:,} 件")
    print(f"  捕まえた / 見逃した / 空振り: {card['tp']:,} / {card['fn']:,} / {card['fp']:,} 件")
    print(f"Brier スコア        : {card['brier']:.5f}")
    print(f"予測確率の平均      : {card['mean_proba']:.4f}（実際の正例率 {card['positive_rate']:.4f}）")
    print("※ accuracy は載せない（「全部しない」と答えても同じ値になるため）")


def roc_points(y_true, proba):
    """ROC 曲線の点（FPR・TPR・閾値）。"""
    return roc_curve(y_true, proba)


def pr_points(y_true, proba):
    """PR 曲線の点（適合率・再現率・閾値）。"""
    return precision_recall_curve(y_true, proba)


def save_figure(fig, name: str) -> Path:
    """図を outputs/ に保存してパスを返す（MPLBACKEND=Agg なので show は使わない）。"""
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / name
    fig.savefig(path, dpi=100)
    return path
