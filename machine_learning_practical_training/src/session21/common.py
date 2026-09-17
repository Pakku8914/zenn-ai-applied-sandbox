"""セッション 21 の本文・練習問題・解答で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import fit_predict_all, regression_scores, score_all

    y_test, preds = fit_predict_all()
    scores = regression_scores(y_test, preds["LightGBM"])

このディレクトリのスクリプトは、他のセッションのディレクトリを一切参照しません
（読者がこの章のファイルだけを作って実行できるようにするためです）。
"""

from __future__ import annotations

from pathlib import Path

import lightgbm as lgb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import (
    mean_absolute_error,
    mean_absolute_percentage_error,
    r2_score,
    root_mean_squared_error,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# データ分割の条件は全章で共通（本書の規約）。回帰なので層化はしない
TEST_SIZE = 0.25
RANDOM_STATE = 42
N_ESTIMATORS = 200  # LightGBM の木の本数（セッション19と同じ条件）

TARGET = "rating"
NUMERIC = ["unit_price", "pages", "published_year", "body_length"]
CATEGORICAL = ["category"]
FEATURES = NUMERIC + CATEGORICAL  # 分類で使ってきた 5 列と同じ構成

# モデルの呼び名。表示の順番もここで決める
LINEAR = "線形回帰"
LGBM = "LightGBM"
MEAN = "平均予測"
MODEL_ORDER = [LINEAR, LGBM, MEAN]

CONSTANT_GUESS = 3.0  # 「全部 3.0」と答えるだけのモデル（R2 が負になる例）
OUTLIER_STAR = 10.0  # 星 10 という実在しない値（外れ値の影響を測る実験用）
STARS = [3.0, 4.0, 5.0]  # 残差を星ごとに見るときに使う（星 1・星 2 は件数が少なすぎる）

METRIC_KEYS = ["mae", "rmse", "mape", "r2"]
LABEL_WIDTH = 10  # モデル名の表示幅
ID_COLUMNS = {"review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str"}


def load_rated_reviews() -> pd.DataFrame:
    """星が入っているレビュー 14,169 件に書籍の情報と注文の単価を結合して返す。

    セッション17〜20 の分類で使ってきた表とまったく同じ作り方・同じ並びです。
    **行を並べ替えません。** train_test_split は行の位置で分割するため、
    並べ替えを挟むと同じ random_state でも別の分割になります（本書の規約）。
    """
    books = pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"})
    reviews = pd.read_csv(DATA_DIR / "reviews.csv", dtype=ID_COLUMNS)
    orders = pd.read_csv(
        DATA_DIR / "orders.csv",
        dtype={"order_id": "str"},
        usecols=["order_id", "unit_price"],
    )
    return (
        reviews.dropna(subset=["rating"])  # 星の欠損 298 件を落とす（セッション11）
        .merge(books, on="book_id", how="left")
        .merge(orders.drop_duplicates("order_id"), on="order_id", how="left")
    )


def split_xy(df: pd.DataFrame):
    """特徴量と目的変数を訓練 10,626 件・評価 3,543 件に分ける（層化はしない）。"""
    return train_test_split(df[FEATURES], df[TARGET], test_size=TEST_SIZE, random_state=RANDOM_STATE)


def make_preprocess() -> ColumnTransformer:
    """数値 4 列を標準化し、category を 0/1 の 5 列に開く（引数は常に明示する）。"""
    return ColumnTransformer(
        [
            ("num", StandardScaler(), NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
        ]
    )


def make_models() -> dict[str, Pipeline]:
    """比べる 3 つのモデル。前処理をそろえてあるので条件は完全に同じ。

    平均予測（DummyRegressor）は特徴量を一切見ません。前処理を通しているのは
    「同じ手順で扱う」ためだけで、返す値は訓練データの星の平均という定数です。
    """
    return {
        LINEAR: Pipeline([("pre", make_preprocess()), ("model", LinearRegression())]),
        LGBM: Pipeline(
            [
                ("pre", make_preprocess()),
                ("model", lgb.LGBMRegressor(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, verbose=-1)),
            ]
        ),
        MEAN: Pipeline([("pre", make_preprocess()), ("model", DummyRegressor(strategy="mean"))]),
    }


def fit_predict_all(df: pd.DataFrame | None = None):
    """3 つのモデルを同じ分割で学習し、評価データの実測と予測を返す。

    返り値は (y_test, {モデル名: 予測値の配列}) です。
    """
    frame = load_rated_reviews() if df is None else df
    X_train, X_test, y_train, y_test = split_xy(frame)
    preds: dict[str, np.ndarray] = {}
    for name, model in make_models().items():
        model.fit(X_train, y_train)
        preds[name] = np.asarray(model.predict(X_test), dtype="float64")
    return y_test, preds


def regression_scores(y_true, pred) -> dict[str, float]:
    """回帰の 4 指標をまとめて返す。1 つだけ返す関数を作らないのがこの章の主題。"""
    return {
        "mae": float(mean_absolute_error(y_true, pred)),
        # sklearn 1.9 には root_mean_squared_error がある（mean_squared_error の squared 引数は廃止済み）
        "rmse": float(root_mean_squared_error(y_true, pred)),
        # 返り値は割合。0.1018 は「平均 10.18% ずれている」という意味
        "mape": float(mean_absolute_percentage_error(y_true, pred)),
        "r2": float(r2_score(y_true, pred)),
    }


def score_all(y_true, preds: dict[str, np.ndarray]) -> dict[str, dict[str, float]]:
    """モデルごとに 4 指標を測った結果をまとめる。"""
    return {name: regression_scores(y_true, pred) for name, pred in preds.items()}


def best_model(scores: dict[str, dict[str, float]], metric: str) -> str:
    """指標ごとにいちばん良いモデルの名前を返す（R2 だけは大きいほうが良い）。"""
    if metric == "r2":
        return max(scores, key=lambda name: scores[name][metric])
    return min(scores, key=lambda name: scores[name][metric])


def constant_prediction(y_true, value: float) -> np.ndarray:
    """どの行にも同じ値を返すだけの予測（定数モデル）。"""
    return np.full(len(y_true), float(value))


def residuals(y_true, pred) -> np.ndarray:
    """残差 ＝ 実測 − 予測。符号の向きを章の中で絶対に変えないこと。"""
    return np.asarray(y_true, dtype="float64") - np.asarray(pred, dtype="float64")


def residual_summary(res: np.ndarray) -> dict[str, float]:
    """残差の平均・標準偏差（ddof=0）・最大絶対値。"""
    return {
        "mean": float(np.mean(res)),
        "std": float(np.std(res)),
        "max_abs": float(np.max(np.abs(res))),
    }


def residual_table(y_true, pred) -> pd.DataFrame:
    """実測・予測・残差を 1 行 1 件で持つ表（プロットと集計の材料）。"""
    return pd.DataFrame(
        {
            "actual": np.asarray(y_true, dtype="float64"),
            "pred": np.asarray(pred, dtype="float64"),
            "residual": residuals(y_true, pred),
        }
    )


def residual_by_actual(y_true, pred) -> pd.DataFrame:
    """実測の星ごとに、件数・残差の平均・予測の平均を集計する。"""
    table = residual_table(y_true, pred)
    grouped = table.groupby("actual").agg(
        count=("residual", "size"),
        residual_mean=("residual", "mean"),
        pred_mean=("pred", "mean"),
    )
    return grouped


def print_scores(label: str, scores: dict[str, float]) -> None:
    """モデル 1 つぶんの 4 指標を 1 行で表示する。"""
    print(
        f"{label:<{LABEL_WIDTH}} MAE {scores['mae']:.4f} / RMSE {scores['rmse']:.4f}"
        f" / MAPE {scores['mape']:.4f} / R2 {scores['r2']:+.4f}"
    )


def print_best(scores: dict[str, dict[str, float]]) -> None:
    """指標ごとの勝者を並べて表示する（指標を 1 つしか見ないと結論が変わることの確認）。"""
    for metric in METRIC_KEYS:
        print(f"{metric.upper():<4}: {best_model(scores, metric)}")


def save_figure(fig, filename: str) -> Path:
    """図を outputs/ に保存する。MPLBACKEND=Agg なので plt.show() は使わない。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / filename
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print(f"図を保存しました: outputs/{filename}")
    return path


def make_toy() -> pd.DataFrame:
    """手計算で確かめられる 5 件。指標の性格の違いを見るために使う。

    モデルA は 4 件を 0.5 ずつ外し、モデルB は 4 件を完全に当てて 1 件だけ 2.0 外します。
    """
    return pd.DataFrame(
        {
            "actual": [3.0, 4.0, 4.0, 5.0, 4.0],
            "model_a": [3.5, 3.5, 4.5, 4.5, 4.0],
            "model_b": [3.0, 4.0, 4.0, 5.0, 6.0],
        }
    )
