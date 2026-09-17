"""セッション 16 の本文・練習問題・解答で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import fit_linear, load_rated_reviews, split_xy

    df = load_rated_reviews()
    X_train, X_test, y_train, y_test = split_xy(df)
    model = fit_linear(X_train, y_train)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from statsmodels.stats.outliers_influence import variance_inflation_factor

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# データ分割の条件は全章で共通（本書の規約）。回帰なので層化はしない
TEST_SIZE = 0.25
RANDOM_STATE = 42

TARGET = "rating"
FEATURES = ["price", "pages", "published_year", "body_length"]
# 刊行年（p 値が大きく有意でない列）を外した 3 列。多重共線性の実演に使う
CORE_FEATURES = ["price", "pages", "body_length"]

# 正則化の強さは手で数段階だけ試す（自動探索は「セッション23：ハイパーパラメータ探索」の仕事）
RIDGE_ALPHAS = [0.1, 1.0, 10.0, 100.0]
LASSO_ALPHAS = [0.001, 0.01, 0.1, 1.0]

# 図のラベルは日本語で書く（本書の方針）
LABEL_JA = {
    "price": "価格",
    "pages": "ページ数",
    "published_year": "刊行年",
    "body_length": "本文の長さ",
    "pages_dup": "ページ数の写し",
}

ID_COLUMNS = {"review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str"}


def load_rated_reviews() -> pd.DataFrame:
    """星が入っているレビュー 14,169 件に書籍の情報を結合して返す。

    **行の並びは merge した直後のまま変えません。** train_test_split は行の位置で
    分割するため、並べ替えを挟むと同じ random_state でも別の分割になります（本書の規約）。
    """
    books = pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"})
    reviews = pd.read_csv(DATA_DIR / "reviews.csv", dtype=ID_COLUMNS, parse_dates=["reviewed_at"])
    rated = reviews.dropna(subset=["rating"])  # 星の欠損 298 件を落とす
    return rated.merge(books, on="book_id", how="left")


def split_xy(df: pd.DataFrame, features: list[str] | None = None):
    """特徴量と目的変数を訓練 10,626 件・評価 3,543 件に分ける。"""
    columns = FEATURES if features is None else features
    return train_test_split(df[columns], df[TARGET], test_size=TEST_SIZE, random_state=RANDOM_STATE)


def fit_linear(X_train: pd.DataFrame, y_train: pd.Series) -> LinearRegression:
    """最小二乗法で直線（超平面）を 1 本引く。設定するものは何もない。"""
    return LinearRegression().fit(X_train, y_train)


def coef_series(model, columns) -> pd.Series:
    """係数に列名を付けて返す。位置（0 番目、1 番目…）で読むと必ず取り違える。"""
    return pd.Series(model.coef_, index=list(columns))


def regression_scores(model, X_test: pd.DataFrame, y_test: pd.Series) -> dict[str, float]:
    """評価データでの R2・MAE・RMSE を返す（指標の詳しい意味はセッション21で扱う）。"""
    pred = model.predict(X_test)
    return {
        "r2": float(r2_score(y_test, pred)),
        "mae": float(mean_absolute_error(y_test, pred)),
        # RMSE は「平均二乗誤差の平方根」。定義が見える形で書いておく
        "rmse": float(np.sqrt(mean_squared_error(y_test, pred))),
    }


def standardize(X_train: pd.DataFrame, X_test: pd.DataFrame):
    """訓練データだけで平均と標準偏差を決め、両方を同じ尺度に直す（列名は保つ）。"""
    scaler = StandardScaler().fit(X_train)  # fit は訓練データだけ（セッション12の規約）
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


def make_toy_line() -> pd.DataFrame:
    """手計算で確かめられる 5 点。最小二乗法の説明に使う。"""
    return pd.DataFrame({"x": [1, 2, 3, 4, 5], "y": [3, 4, 6, 7, 10]})


def line_pred(x, slope: float, intercept: float) -> np.ndarray:
    """傾きと切片を決め打ちした直線の予測値。"""
    return intercept + slope * np.asarray(x, dtype="float64")


def sse(y, y_hat) -> float:
    """残差二乗和。最小二乗法が小さくしようとしている値そのもの。"""
    diff = np.asarray(y, dtype="float64") - np.asarray(y_hat, dtype="float64")
    return float((diff**2).sum())


def print_coefs(coefs: pd.Series, intercept: float | None = None) -> None:
    """係数を 1 行 1 列で表示する。全角 2 文字ぶんを見込んで桁をそろえている。"""
    for name, value in coefs.items():
        print(f"{name:<15}: {value:+.6f}")
    if intercept is not None:
        print(f"{'切片':<13}: {intercept:+.4f}")


def nonzero_columns(coefs: pd.Series) -> list[str]:
    """係数がちょうど 0 でない列の名前（Lasso の変数選択の結果を読むため）。"""
    return [str(name) for name, value in coefs.items() if value != 0.0]


def zero_columns(coefs: pd.Series) -> list[str]:
    """係数がちょうど 0 になった列の名前。"""
    return [str(name) for name, value in coefs.items() if value == 0.0]


def fit_penalized(model, X_train_s: pd.DataFrame, y_train: pd.Series, X_test_s: pd.DataFrame, y_test: pd.Series):
    """Ridge / Lasso を学習し、係数（列名付き）と評価データの R2 を返す。"""
    model.fit(X_train_s, y_train)
    return coef_series(model, X_train_s.columns), float(r2_score(y_test, model.predict(X_test_s)))
