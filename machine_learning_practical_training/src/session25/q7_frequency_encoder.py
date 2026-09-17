"""問題7 の解答: 訓練データから「水準の出現比率」を覚える独自クラスを書く。

実行:
    docker compose exec lab python src/session25/q7_frequency_encoder.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from common import (
    CATEGORICAL,
    MAX_ITER,
    NUMERIC,
    RANDOM_STATE,
    auc_of,
    cv_auc,
    features_target,
    load_review_table,
    numeric_steps,
    split,
    summarize,
)

C_VALUES = [0.01, 1.0, 100.0]  # set_params で差し替える正則化の強さ（セッション16）
UNKNOWN_ROW = {"category": "写真集", "region": "北海道", "channel": "SNS"}


class FrequencyEncoder(TransformerMixin, BaseEstimator):
    """カテゴリを「訓練データでの出現比率」1 列に置き換える変換。

    比率は fit のときにだけ数えます。transform では覚えた比率を当てるだけなので、
    評価データの件数は比率に影響しません。訓練データに無かった水準は unknown_value にします。
    """

    def __init__(self, unknown_value: float = 0.0) -> None:
        self.unknown_value = unknown_value

    @staticmethod
    def _to_frame(X) -> pd.DataFrame:
        if isinstance(X, pd.DataFrame):
            return X
        return pd.DataFrame(np.asarray(X, dtype=object))

    def fit(self, X, y=None) -> "FrequencyEncoder":
        frame = self._to_frame(X)
        self.n_features_in_ = frame.shape[1]
        self.feature_names_in_ = np.asarray([str(c) for c in frame.columns], dtype=object)
        self.frequencies_ = {
            column: frame[column].value_counts(normalize=True) for column in frame.columns
        }
        return self

    def transform(self, X) -> np.ndarray:
        frame = self._to_frame(X)
        values = np.empty((len(frame), self.n_features_in_), dtype="float64")
        for index, column in enumerate(frame.columns):
            mapped = frame[column].map(self.frequencies_[column]).fillna(self.unknown_value)
            values[:, index] = mapped.to_numpy(dtype="float64")
        return values

    def get_feature_names_out(self, input_features=None) -> np.ndarray:
        base = self.feature_names_in_ if input_features is None else input_features
        return np.asarray([f"{name}_freq" for name in base], dtype=object)


def frequency_pipeline() -> Pipeline:
    """カテゴリ 3 列を One-Hot 16 列ではなく、比率 3 列に置き換える構成。"""
    categorical_steps = Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("freq", FrequencyEncoder(unknown_value=0.0)),
        ]
    )
    preprocess = ColumnTransformer(
        [
            ("num", numeric_steps(), NUMERIC),
            ("cat", categorical_steps, CATEGORICAL),
        ]
    )
    return Pipeline(
        [
            ("pre", preprocess),
            ("model", LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)),
        ]
    )


def analyze(df) -> dict[str, object]:
    """比率エンコーディングの列名と挙動を確かめ、C を差し替えて交差検証する。"""
    X, y = features_target(df)
    X_train, X_test, y_train, y_test = split(X, y)

    pipeline = frequency_pipeline().fit(X_train, y_train)
    pre = pipeline.named_steps["pre"]
    names = [str(name) for name in pre.get_feature_names_out()]

    # 未知の水準の扱いを、変換器だけ取り出して確かめる
    standalone = FrequencyEncoder(unknown_value=0.0).fit(X_train[CATEGORICAL])
    unknown = standalone.transform(pd.DataFrame([UNKNOWN_ROW]))

    rows = []
    for c in C_VALUES:
        estimator = frequency_pipeline()
        estimator.set_params(model__C=c)  # 前処理はそのまま、モデルだけ差し替える
        scores = cv_auc(estimator, X, y)
        mean, std = summarize(scores)
        rows.append({"C": c, "mean": mean, "std": std})

    return {
        "names": names,
        "n_names": len(names),
        "freq_names": [name for name in names if name.endswith("_freq")],
        "sums": {column: float(series.sum()) for column, series in standalone.frequencies_.items()},
        "n_levels": {column: int(len(series)) for column, series in standalone.frequencies_.items()},
        "unknown_value": float(unknown[0][0]),
        "known_values_positive": bool((unknown[0][1:] > 0).all()),
        "holdout": auc_of(pipeline, X_test, y_test),
        "rows": rows,
        "all_beat_chance": bool(all(row["mean"] > 0.5 for row in rows)),
    }


def main() -> None:
    result = analyze(load_review_table())

    print("■ 1. 変換後の列")
    print(f"列の合計   : {result['n_names']} 列")
    print(f"列名       : {result['names']}")
    print(f"比率の列   : {result['freq_names']}")
    for column, count in result["n_levels"].items():
        print(f"  {column:<9}: 水準 {count} 個 / 比率の合計 {result['sums'][column]:.4f}")
    print()

    print("■ 2. 訓練データに無かった水準の扱い")
    print(f"'{UNKNOWN_ROW['category']}' に当たる値 : {result['unknown_value']:.4f}")
    print(f"既知の水準はすべて 0 より大きい       : {result['known_values_positive']}")
    print()

    print("■ 3. C を差し替えて交差検証")
    print(f"ホールドアウト 1 回（C=1.0）: {result['holdout']:.4f}")
    for row in result["rows"]:
        print(f"  C={row['C']:<6}: 平均 {row['mean']:.4f} / 標準偏差 {row['std']:.4f}")
    print(f"どの C でも当て推量を上回る : {result['all_beat_chance']}")


if __name__ == "__main__":
    main()
