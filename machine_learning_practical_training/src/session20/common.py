"""セッション 20 の本文・練習問題・解答で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import fit_high_rating, load_review_table, predict_at

    df = load_review_table()
    y_test, proba = fit_high_rating(df)
    y_pred = predict_at(proba, 0.5)

読み込みと分割の条件は src/verify_setup.py の 5 節（およびセッション17〜19）と同じです。
**行を並べ替えません。** sort_values を挟むと同じ random_state でも別の分割になります（本書の規約）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# データ分割の条件は全章で共通（本書の規約）
TEST_SIZE = 0.25
RANDOM_STATE = 42
MAX_ITER = 1000  # ロジスティック回帰の反復上限（セッション17 と同じ条件）

NUMERIC = ["unit_price", "pages", "published_year", "body_length"]
CATEGORICAL = ["category"]
FEATURES = NUMERIC + CATEGORICAL

# 陽性（1）は「高評価（星 4 以上）」、陰性（0）は「低評価（星 3 以下）」
POSITIVE_LABEL = 1
NEGATIVE_LABEL = 0
CLASS_NAMES = {NEGATIVE_LABEL: "陰性（低評価）", POSITIVE_LABEL: "陽性（高評価）"}

# 確率をクラスに変えるときの境目。0.5 は「既定値」であって「正解」ではない
DEFAULT_THRESHOLD = 0.5
# セッション17 で見た 5 段階（この章でも再掲する）
THRESHOLDS = [0.3, 0.5, 0.7, 0.8, 0.9]
# コストから閾値を決めるときに試す刻み（0.05 から 0.95 まで）
COST_GRID = np.round(np.arange(0.05, 1.00, 0.05), 2)
# (見逃し 1 件の重み, 誤検出 1 件の重み)
COST_SETTINGS = [(1, 1), (5, 1), (1, 5)]


def load_review_table() -> pd.DataFrame:
    """高評価レビューの分類に使う表を作る（src/verify_setup.py の 5 節と同じ作り方・同じ並び）。

    星が欠損している 298 件を落とし、書籍マスタと注文の単価を結合して 14,169 行にします。
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
    """二値分類（高評価かどうか）の訓練・評価に分ける（条件は全章共通）。"""
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


def prepare(X_train: pd.DataFrame, X_test: pd.DataFrame):
    """前処理を訓練データだけで fit し、両方を transform して列名も返す。"""
    pre = make_preprocess()
    train = pre.fit_transform(X_train)  # fit は訓練データだけ（セッション12）
    test = pre.transform(X_test)  # 評価データは transform だけ
    names = [name.split("__")[-1] for name in pre.get_feature_names_out()]
    return pre, train, test, names


def fit_model(X_train_t, y_train) -> LogisticRegression:
    """ロジスティック回帰を学習する（二値でも多クラスでも同じ呼び方で動く）。"""
    model = LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)
    model.fit(X_train_t, y_train)
    return model


def fit_high_rating(df: pd.DataFrame):
    """高評価の分類を学習し、(評価データの正解, 高評価である予測確率) を返す。"""
    X_train, X_test, y_train, y_test = split_xy(df)
    _, train, test, _ = prepare(X_train, X_test)
    model = fit_model(train, y_train)
    return y_test, model.predict_proba(test)[:, 1]


def predict_at(proba, threshold: float = DEFAULT_THRESHOLD):
    """確率を閾値で切ってクラス（0 / 1）に変える。predict は threshold=0.5 と同じ。"""
    return (np.asarray(proba) >= threshold).astype("int64")


# ------------------------------------------------------------------
# 混同行列とそこから計算する指標
# ------------------------------------------------------------------
def confusion_parts(y_true, y_pred) -> dict[str, int]:
    """混同行列の 4 象限を名前付きで取り出す（labels を明示して並びを固定する）。"""
    matrix = confusion_matrix(y_true, y_pred, labels=[NEGATIVE_LABEL, POSITIVE_LABEL])
    tn, fp, fn, tp = matrix.ravel()
    return {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}


def print_confusion(parts: dict[str, int]) -> None:
    """混同行列を 4 象限の呼び名つきで表示する。"""
    print("                予測:低評価   予測:高評価")
    print(f"実測:低評価   TN {parts['tn']:>6,}   FP {parts['fp']:>6,}")
    print(f"実測:高評価   FN {parts['fn']:>6,}   TP {parts['tp']:>6,}")


def class_metrics(y_true, y_pred, label: int) -> dict[str, float]:
    """1 つのクラスを陽性とみなしたときの適合率・再現率・F1・件数。"""
    return {
        "precision": float(precision_score(y_true, y_pred, pos_label=label, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, pos_label=label, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, pos_label=label, zero_division=0)),
        "support": int((np.asarray(y_true) == label).sum()),
    }


def per_class_table(y_true, y_pred) -> pd.DataFrame:
    """陰性・陽性の両方について指標を並べた表を作る（片方だけ見ないための道具）。"""
    rows = []
    for label in (NEGATIVE_LABEL, POSITIVE_LABEL):
        row = {"label": label, "name": CLASS_NAMES[label]}
        row.update(class_metrics(y_true, y_pred, label))
        rows.append(row)
    return pd.DataFrame(rows)


def print_per_class_table(table: pd.DataFrame) -> None:
    """クラスごとの指標を 1 行 1 クラスで表示する。"""
    print("クラス          | 適合率 | 再現率 |   F1   | 件数")
    for row in table.itertuples(index=False):
        print(f"{row.name}  | {row.precision:.4f} | {row.recall:.4f} | {row.f1:.4f} | {row.support:>5,}")


def average_scores(y_true, y_pred) -> dict[str, float]:
    """平均の取り方を変えた F1 と accuracy。二値でも多クラスでも同じ関数で計算できる。

    macro    : クラスごとの F1 を単純平均する（少数クラスも 1 票）
    weighted : クラスごとの F1 を件数で重みづけて平均する（多数クラスの声が大きい）
    micro    : クラスを区別せず全件をまとめて数える（単一ラベルの分類では accuracy と一致する）
    """
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro")),
        "weighted_f1": float(f1_score(y_true, y_pred, average="weighted")),
        "micro_f1": float(f1_score(y_true, y_pred, average="micro")),
    }


def baseline_scores(y_true) -> dict[str, float]:
    """「全部 高評価」と答えるだけのベースライン（多数クラス予測）。"""
    y_true_array = np.asarray(y_true)
    always_one = np.ones(len(y_true_array), dtype="int64")
    constant_score = np.full(len(y_true_array), 0.5)  # 全員同じ点数なので順位が付かない
    return {
        "accuracy": float(accuracy_score(y_true_array, always_one)),
        "roc_auc": float(roc_auc_score(y_true_array, constant_score)),
        "pr_auc": float(average_precision_score(y_true_array, constant_score)),
    }


# ------------------------------------------------------------------
# 閾値に依存しない指標（ROC と PR）
# ------------------------------------------------------------------
def curve_scores(y_true, proba) -> dict[str, float]:
    """ROC AUC と PR-AUC、それに評価データの正例率（PR 曲線のベースライン）。"""
    return {
        "roc_auc": float(roc_auc_score(y_true, proba)),
        "pr_auc": float(average_precision_score(y_true, proba)),
        "positive_rate": float(np.mean(np.asarray(y_true) == POSITIVE_LABEL)),
    }


def roc_points(y_true, proba):
    """ROC 曲線の点（FPR・TPR・閾値）。"""
    return roc_curve(y_true, proba)


def pr_points(y_true, proba):
    """PR 曲線の点（適合率・再現率・閾値）。"""
    return precision_recall_curve(y_true, proba)


def youden_point(y_true, proba) -> dict[str, float]:
    """Youden 指標（TPR - FPR）が最大になる点を ROC 曲線の上から探す。"""
    fpr, tpr, thresholds = roc_curve(y_true, proba)
    index = int(np.argmax(tpr - fpr))
    return {
        "threshold": float(thresholds[index]),
        "tpr": float(tpr[index]),
        "fpr": float(fpr[index]),
        "youden": float(tpr[index] - fpr[index]),
    }


# ------------------------------------------------------------------
# 閾値を動かす・コストから閾値を決める
# ------------------------------------------------------------------
def threshold_metrics(y_true, proba, threshold: float) -> dict[str, float]:
    """閾値を 1 つ決めて、陽性と予測した件数・適合率・再現率・F1・accuracy を返す。"""
    y_pred = predict_at(proba, threshold)
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


def cost_row(y_true, proba, threshold: float, miss_cost: float, alarm_cost: float) -> dict[str, float]:
    """閾値 1 つぶんの「見逃し（FN）・誤検出（FP）・総コスト」を返す。"""
    parts = confusion_parts(y_true, predict_at(proba, threshold))
    return {
        "threshold": float(threshold),
        "n_miss": parts["fn"],  # 高評価なのに拾えなかった（機会損失）
        "n_alarm": parts["fp"],  # 低評価を高評価として拾ってしまった（信用の損失）
        "total_cost": float(parts["fn"] * miss_cost + parts["fp"] * alarm_cost),
    }


def cost_table(y_true, proba, miss_cost: float, alarm_cost: float, grid=None) -> pd.DataFrame:
    """0.05 刻みの閾値について総コストを並べた表を作る。"""
    targets = COST_GRID if grid is None else grid
    return pd.DataFrame([cost_row(y_true, proba, t, miss_cost, alarm_cost) for t in targets])


def best_cost_threshold(y_true, proba, miss_cost: float, alarm_cost: float, grid=None) -> dict[str, float]:
    """総コストが最小になる閾値を返す（同点なら小さい閾値を選ぶ）。"""
    table = cost_table(y_true, proba, miss_cost, alarm_cost, grid)
    row = table.loc[table["total_cost"].idxmin()]
    return {
        "threshold": float(row["threshold"]),
        "n_miss": int(row["n_miss"]),
        "n_alarm": int(row["n_alarm"]),
        "total_cost": float(row["total_cost"]),
    }


# ------------------------------------------------------------------
# 多クラス分類（星 1〜5 をそのまま予測する）
# ------------------------------------------------------------------
def star_counts(df: pd.DataFrame) -> pd.Series:
    """星ごとの件数を星の小さい順に並べる。"""
    return df["rating"].astype("int64").value_counts().sort_index()


def split_star(df: pd.DataFrame, stratify: bool = False):
    """星 1〜5 を目的変数にして分割する。stratify=True にすると ValueError になる。"""
    X = df[FEATURES]
    y = df["rating"].astype("int64")
    return train_test_split(
        X,
        y,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=y if stratify else None,
    )


def stratify_error_message(df: pd.DataFrame) -> str:
    """層化分割を試して、出た ValueError の文面を返す（教材として実演するための関数）。"""
    try:
        split_star(df, stratify=True)
    except ValueError as error:
        return str(error)
    raise AssertionError("ValueError が出ませんでした（データが変わった可能性があります）")


def fit_star_model(df: pd.DataFrame):
    """星 1〜5 の 5 クラス分類を学習し、(正解, 予測, モデル) を返す。"""
    X_train, X_test, y_train, y_test = split_star(df)
    _, train, test, _ = prepare(X_train, X_test)
    model = fit_model(train, y_train)
    return y_test, model.predict(test), model


def multiclass_confusion(y_true, y_pred):
    """実測と予測に現れたクラスだけを使った混同行列（labels と行列を返す）。"""
    labels = sorted(set(int(v) for v in np.unique(y_true)) | set(int(v) for v in np.unique(y_pred)))
    return labels, confusion_matrix(y_true, y_pred, labels=labels)


def print_multiclass_confusion(labels, matrix) -> None:
    """多クラスの混同行列を表示する（行 = 実測の星、列 = 予測の星）。"""
    print("（行 = 実測の星、列 = 予測の星）")
    print("       " + "".join(f"{label:>7}" for label in labels))
    for label, row in zip(labels, matrix):
        cells = "".join(f"{int(value):>7,}" for value in row)
        print(f"星 {label}   {cells}")


def save_figure(fig, name: str) -> Path:
    """図を outputs/ に保存してパスを返す（MPLBACKEND=Agg なので show は使わない）。"""
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / name
    fig.savefig(path, dpi=100)
    return path
