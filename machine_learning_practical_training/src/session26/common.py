"""セッション 26 の本文・練習問題・解答で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import fitted, impurity_table, permutation_table, shap_bundle

    bundle = fitted()                  # 高評価分類の LightGBM（同じ条件なら再学習しない）
    table = impurity_table()           # 不純度ベースの重要度（split と gain）
    perm = permutation_table("test")   # permutation importance（評価データ）

このディレクトリのスクリプトは、他のセッションのディレクトリを一切参照しません
（読者がこの章のファイルだけを作って実行できるようにするためです）。
"""

from __future__ import annotations

import warnings
from functools import lru_cache
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import shap
from sklearn.compose import ColumnTransformer
from sklearn.inspection import partial_dependence, permutation_importance
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# データ分割と乱数の条件は全章で共通（本書の規約）
TEST_SIZE = 0.25
RANDOM_STATE = 42

# 高評価レビューの分類（src/verify_setup.py の 5 節と同じ条件）
N_ESTIMATORS = 200
NUMERIC = ["unit_price", "pages", "published_year", "body_length"]
CATEGORICAL = ["category"]
FEATURES = NUMERIC + CATEGORICAL

# permutation importance の条件
N_REPEATS = 5  # 1 つの列を何回シャッフルするか
SCORING = "roc_auc"  # 「性能がどれだけ落ちたか」を測る指標

# 部分依存プロットの条件
GRID_RESOLUTION = 5  # 1 つの列を何点に区切って動かすか

# SHAP の条件（src/verify_setup.py の 7 節と同じ条件）
SHAP_N_ESTIMATORS = 50
SHAP_ROWS = 100

# 高カーディナリティの罠を作るための「意味のない列」
RANDOM_ID = "random_id"
RANDOM_ID_MAX = 10000


def load_review_table() -> pd.DataFrame:
    """高評価レビューの分類に使う表を作る（src/verify_setup.py の 5 節と同じ作り方・同じ並び）。

    星が欠損している 298 件を落とし、書籍マスタと注文の単価を結合して 14,169 行にします。
    **並べ替えません。** sort_values を挟むと同じ random_state でも別の分割になります（本書の規約）。
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


def add_random_id(df: pd.DataFrame) -> pd.DataFrame:
    """0〜9,999 の意味のない整数列を足す。

    **分割の前に一度だけ**振ります。訓練データと評価データに別々に振ると、
    同じ `random_state` でも別の乱数列になり、この章の数値が再現しません。
    """
    rng = np.random.default_rng(RANDOM_STATE)
    return df.assign(**{RANDOM_ID: rng.integers(0, RANDOM_ID_MAX, len(df))})


def make_preprocess(numeric: list[str]) -> ColumnTransformer:
    """数値列を標準化し、category を 0/1 の 5 列に開く（引数は常に明示する）。"""
    return ColumnTransformer(
        [
            ("num", StandardScaler(), numeric),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
        ]
    )


def clean_names(pre: ColumnTransformer) -> list[str]:
    """ColumnTransformer が付ける接頭辞（num__ / cat__）を落として読みやすくする。"""
    return [name.split("__")[-1] for name in pre.get_feature_names_out()]


@lru_cache(maxsize=None)
def fitted(with_random_id: bool = False) -> dict:
    """高評価分類の Pipeline を学習し、この章で使う道具をまとめて返す。

    `lru_cache` を付けているので、同じ引数なら 2 回目以降は学習をやり直しません
    （この章は同じモデルを何度も覗き込むため）。呼び出しは `fitted()` か
    `fitted(True)` のどちらかにそろえてください（キーワード指定にすると別扱いになります）。
    """
    df = load_review_table()
    numeric = list(NUMERIC)
    if with_random_id:
        df = add_random_id(df)
        numeric = numeric + [RANDOM_ID]  # 数値列の末尾に足す
    features = numeric + CATEGORICAL

    X_train, X_test, y_train, y_test = train_test_split(
        df[features],
        df["is_high"],
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=df["is_high"],
    )
    pipeline = Pipeline(
        [
            ("pre", make_preprocess(numeric)),
            ("model", lgb.LGBMClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, verbose=-1)),
        ]
    ).fit(X_train, y_train)

    proba = pipeline.predict_proba(X_test)[:, 1]
    return {
        "df": df,
        "features": features,
        "numeric": numeric,
        "X_train": X_train,
        "X_test": X_test,
        "y_train": y_train,
        "y_test": y_test,
        "pipeline": pipeline,
        "names": clean_names(pipeline["pre"]),  # 変換後の列名（One-Hot で開いた後）
        "roc_auc": float(roc_auc_score(y_test, proba)),
    }


def impurity_table(with_random_id: bool = False) -> pd.DataFrame:
    """不純度ベースの重要度を 2 通り（split と gain）取り出して並べる。

    - split: その列が分割に使われた回数
    - gain : その列の分割で減った不純度の合計

    どちらも「学習した木の形」から数えるだけなので、データを 1 行も predict しません。
    """
    bundle = fitted(with_random_id)
    booster = bundle["pipeline"]["model"].booster_
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
    """permutation importance を計算して大きい順に並べる。

    `which="test"` なら評価データ、`"train"` なら訓練データで測ります。
    Pipeline をそのまま渡すので、**シャッフルするのは前処理より前の元の列**です
    （だから `category` は One-Hot で開いた 5 列ではなく 1 つの列として扱われます）。
    """
    bundle = fitted(with_random_id)
    X = bundle["X_test"] if which == "test" else bundle["X_train"]
    y = bundle["y_test"] if which == "test" else bundle["y_train"]
    result = permutation_importance(
        bundle["pipeline"],
        X,
        y,
        scoring=SCORING,
        n_repeats=N_REPEATS,
        random_state=RANDOM_STATE,
    )
    table = pd.DataFrame(
        {
            "feature": bundle["features"],
            "mean": result.importances_mean,
            "std": result.importances_std,
        }
    )
    return table.sort_values("mean", ascending=False).reset_index(drop=True)


@lru_cache(maxsize=None)
def shap_bundle() -> dict:
    """SHAP の計算をまとめて行う（src/verify_setup.py の 7 節と同じ条件）。

    数値 4 列だけを特徴量にし、全 14,169 件で木 50 本のモデルを学習して、
    先頭 100 行を説明します。`TreeExplainer` が出す警告は**隠さずに捕まえて**
    呼び出し側に返します（警告の内容もこの章の教材です）。
    """
    df = load_review_table()
    frame = df[NUMERIC]  # One-Hot も標準化もせず、そのまま木に渡す
    model = lgb.LGBMClassifier(
        n_estimators=SHAP_N_ESTIMATORS, random_state=RANDOM_STATE, verbose=-1
    ).fit(frame, df["is_high"])

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")  # filterwarnings("ignore") で消してはいけない
        explainer = shap.TreeExplainer(model)
        values = np.asarray(explainer.shap_values(frame.head(SHAP_ROWS)))

    base = explainer.expected_value
    return {
        "model": model,
        "frame": frame,
        "explainer": explainer,
        "values": values,
        "base": float(base),
        "base_dtype": str(np.asarray(base).dtype),
        "base_shape": np.asarray(base).shape,
        # 警告は全文が長いので、冒頭 79 文字だけを取り出しておく
        "warnings": [
            f"{w.category.__name__}: {str(w.message)[:79]} ..."
            for w in caught
            if "TreeExplainer" in str(w.message)
        ],
    }


def sigmoid(x: float) -> float:
    """対数オッズを 0〜1 の確率に変換する（セッション17 で使ったものと同じ）。"""
    return float(1.0 / (1.0 + np.exp(-x)))


def shap_mean_abs() -> pd.DataFrame:
    """SHAP 値の平均絶対値で「全体としてどの列が効いたか」を並べる。"""
    bundle = shap_bundle()
    table = pd.DataFrame({"feature": NUMERIC, "mean_abs": np.abs(bundle["values"]).mean(axis=0)})
    return table.sort_values("mean_abs", ascending=False).reset_index(drop=True)


def shap_local(row: int = 0) -> pd.DataFrame:
    """1 行ぶんの予測を、特徴量ごとの寄与に分解して並べる（局所的説明）。"""
    bundle = shap_bundle()
    table = pd.DataFrame(
        {
            "feature": NUMERIC,
            "value": bundle["frame"].iloc[row].to_numpy(),
            "shap": bundle["values"][row],
        }
    )
    return table.sort_values("shap", ascending=False).reset_index(drop=True)


def shap_local_check(row: int = 0) -> dict:
    """加法性（SHAP 値の合計 + 基準値 = 予測）が成り立つことを確かめる。"""
    bundle = shap_bundle()
    total = float(bundle["values"][row].sum())
    logit = total + bundle["base"]
    from_model = float(bundle["model"].predict_proba(bundle["frame"].iloc[[row]])[0, 1])
    return {
        "total": total,
        "base": bundle["base"],
        "logit": logit,
        "proba_from_shap": sigmoid(logit),
        "proba_from_model": from_model,
        "matches": bool(abs(sigmoid(logit) - from_model) < 1e-6),
    }


def to_float(X: pd.DataFrame, numeric: list[str]) -> pd.DataFrame:
    """partial_dependence は int 型の列を受け付けないので float64 にしてから渡す。"""
    return X.astype({name: "float64" for name in numeric})


def pdp_table(feature: str, with_random_id: bool = False) -> pd.DataFrame:
    """1 つの列だけを動かしたときの「予測確率の平均」を表にする（部分依存）。

    平均を取るデータは**訓練データ**です。グリッドの刻みは渡したデータの分位から
    決まり、平均もそのデータの上で取るので、**渡すデータを変えると数値が変わります**
    （評価データで取ると別の値になります）。どちらで取ったかを必ず添えて報告します。
    """
    bundle = fitted(with_random_id)
    X = to_float(bundle["X_train"], bundle["numeric"])  # 訓練データで平均を取る
    result = partial_dependence(bundle["pipeline"], X, [feature], grid_resolution=GRID_RESOLUTION)
    return pd.DataFrame({"grid": result["grid_values"][0], "average": result["average"][0]})


def pdp_int_error(feature: str = "unit_price") -> str:
    """int 型のまま渡すと ValueError になることを確かめ、その文面を返す。"""
    bundle = fitted()
    try:
        partial_dependence(
            bundle["pipeline"], bundle["X_train"], [feature], grid_resolution=GRID_RESOLUTION
        )
    except ValueError as exc:
        return str(exc)
    return ""  # 例外が出なければ空文字（環境が変わったサイン）


def save_figure(fig, name: str) -> Path:
    """図を outputs/ に保存してパスを返す（MPLBACKEND=Agg なので show は使わない）。"""
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / name
    fig.savefig(path, dpi=100)
    return path
