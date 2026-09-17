"""自作の変換を Pipeline に組み込む 2 通りの方法（本文 5 節）。

① FunctionTransformer  : 状態を持たない変換（np.log1p など）をその場で包む
② 独自クラス           : 訓練データから何かを覚える変換（分位点など）を自分で書く

実行:
    docker compose exec lab python src/session25/custom_transformers.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from common import (
    CATEGORICAL,
    MAX_ITER,
    NUMERIC,
    RANDOM_STATE,
    auc_of,
    categorical_steps,
    cv_auc,
    features_target,
    load_review_table,
    numeric_steps,
    split,
    summarize,
)

LOG_COLUMNS = ["body_length"]                                   # log1p を通す列
PLAIN_COLUMNS = [c for c in NUMERIC if c not in LOG_COLUMNS]    # そのまま標準化する 3 列
LOWER_QUANTILE = 0.01
UPPER_QUANTILE = 0.99


class QuantileClipper(TransformerMixin, BaseEstimator):
    """訓練データの分位点を覚え、その範囲の外に出た値を境界まで引き戻す変換。

    セッション12 で手で書いた外れ値の処理を、Pipeline に載せられる形にしたものです。
    **境界は fit のときにだけ決めます。** transform では覚えた境界を使うだけなので、
    評価データの分布は境界に影響しません（これがリークを防ぐ仕組みです）。

    Mixin を BaseEstimator より先に書くのは scikit-learn の作法です（1.6 以降、
    推定器の性質を伝える仕組みが Mixin 側にあるため、順番を逆にすると噛み合いません）。
    """

    def __init__(self, lower: float = LOWER_QUANTILE, upper: float = UPPER_QUANTILE) -> None:
        # __init__ では受け取った値をそのまま持つだけにする（scikit-learn の約束）
        self.lower = lower
        self.upper = upper

    @staticmethod
    def _to_frame(X) -> pd.DataFrame:
        if isinstance(X, pd.DataFrame):
            return X
        return pd.DataFrame(np.asarray(X, dtype="float64"))

    def fit(self, X, y=None) -> "QuantileClipper":
        frame = self._to_frame(X)
        self.n_features_in_ = frame.shape[1]
        self.feature_names_in_ = np.asarray([str(c) for c in frame.columns], dtype=object)
        self.lower_bounds_ = frame.quantile(self.lower).to_numpy(dtype="float64")
        self.upper_bounds_ = frame.quantile(self.upper).to_numpy(dtype="float64")
        return self

    def transform(self, X) -> np.ndarray:
        frame = self._to_frame(X)
        values = frame.to_numpy(dtype="float64")
        return np.clip(values, self.lower_bounds_, self.upper_bounds_)

    def get_feature_names_out(self, input_features=None) -> np.ndarray:
        if input_features is not None:
            return np.asarray([str(name) for name in input_features], dtype=object)
        return self.feature_names_in_


def log_preprocess() -> ColumnTransformer:
    """body_length だけ log1p を通してから標準化する枝を足した ColumnTransformer。"""
    log_steps = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            # 状態を持たない変換は FunctionTransformer で包むだけで 1 段になる
            ("log", FunctionTransformer(np.log1p, feature_names_out="one-to-one")),
            ("scale", StandardScaler()),
        ]
    )
    return ColumnTransformer(
        [
            ("log", log_steps, LOG_COLUMNS),
            ("num", numeric_steps(), PLAIN_COLUMNS),
            ("cat", categorical_steps(), CATEGORICAL),
        ]
    )


def clipped_preprocess() -> ColumnTransformer:
    """数値列の外れ値を訓練データの分位点でクリップしてから標準化する。"""
    clipped_steps = Pipeline(
        [
            ("clip", QuantileClipper(lower=LOWER_QUANTILE, upper=UPPER_QUANTILE)),
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]
    )
    return ColumnTransformer(
        [
            ("num", clipped_steps, NUMERIC),
            ("cat", categorical_steps(), CATEGORICAL),
        ]
    )


def build(preprocess) -> Pipeline:
    """前処理を差し替えても、外側の形（pre → model）は変わらない。"""
    return Pipeline(
        [
            ("pre", preprocess),
            ("model", LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)),
        ]
    )


def analyze(df) -> dict[str, object]:
    """2 通りの自作変換を組み込み、列名と「境界がどこから来たか」を確かめる。"""
    X, y = features_target(df)
    X_train, X_test, y_train, y_test = split(X, y)

    # ① FunctionTransformer
    log_pipeline = build(log_preprocess()).fit(X_train, y_train)
    log_names = [str(name) for name in log_pipeline.named_steps["pre"].get_feature_names_out()]
    log_auc = auc_of(log_pipeline, X_test, y_test)
    # 変換の中身が np.log1p そのものであることを手計算で確かめる
    log_branch = log_pipeline.named_steps["pre"].named_transformers_["log"]
    manual = np.log1p(X_train[LOG_COLUMNS].to_numpy(dtype="float64"))
    scaled_by_hand = (manual - manual.mean(axis=0)) / manual.std(axis=0)
    log_matches = bool(np.allclose(log_branch.transform(X_train[LOG_COLUMNS]), scaled_by_hand))

    # ② 独自クラス
    clipper = QuantileClipper(lower=LOWER_QUANTILE, upper=UPPER_QUANTILE).fit(X_train[NUMERIC])
    clipped_test = clipper.transform(X_test[NUMERIC])
    raw_test_max = X_test[NUMERIC].to_numpy(dtype="float64").max(axis=0)
    clip_pipeline = build(clipped_preprocess()).fit(X_train, y_train)
    clip_auc = auc_of(clip_pipeline, X_test, y_test)
    scores = cv_auc(build(clipped_preprocess()), X, y)  # fold ごとに境界を学び直す
    cv_mean, cv_std = summarize(scores)

    return {
        "log_names": log_names,
        "log_n_columns": len(log_names),
        "log_matches_manual": log_matches,
        "log_auc": log_auc,
        "clip_columns": list(clipper.feature_names_in_),
        "clip_names_out": [str(n) for n in clipper.get_feature_names_out()],
        "clip_lower": clipper.lower_bounds_,
        "clip_upper": clipper.upper_bounds_,
        "test_within_train_bounds": bool((clipped_test.max(axis=0) <= clipper.upper_bounds_ + 1e-9).all()),
        "test_had_larger_values": bool((raw_test_max > clipper.upper_bounds_).any()),
        "clip_auc": clip_auc,
        "clip_cv_mean": cv_mean,
        "clip_cv_std": cv_std,
    }


def main() -> None:
    result = analyze(load_review_table())

    print("■ 1. FunctionTransformer で log1p を挟む")
    print(f"変換後の列数           : {result['log_n_columns']} 列")
    print(f"先頭 4 列の名前         : {result['log_names'][:4]}")
    print(f"中身が np.log1p と一致  : {result['log_matches_manual']}")
    print(f"ROC AUC                : {result['log_auc']:.4f}")
    print()

    print("■ 2. 独自クラスで分位点クリップを挟む")
    print(f"境界を覚えた列         : {result['clip_columns']}")
    print(f"get_feature_names_out  : {result['clip_names_out']}")
    print(f"評価データに境界より大きい値があった : {result['test_had_larger_values']}")
    print(f"変換後は境界を超えない : {result['test_within_train_bounds']}")
    print(f"ROC AUC                : {result['clip_auc']:.4f}")
    print(
        f"層化 5 分割の平均      : {result['clip_cv_mean']:.4f}"
        f" / 標準偏差 {result['clip_cv_std']:.4f}"
    )


if __name__ == "__main__":
    main()
