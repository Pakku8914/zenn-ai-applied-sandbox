"""問題4 の解答: Pipeline のまま交差検証に渡し、fold ごとに fit されることを確かめる。

実行:
    docker compose exec lab python src/session25/q4_cross_val.py
"""

from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from common import (
    CATEGORICAL,
    CATEGORICAL_S17,
    MAX_ITER,
    NUMERIC,
    RANDOM_STATE,
    build_pipeline,
    build_preprocess,
    cv_auc,
    features_target,
    fmt_scores,
    holdout_auc,
    load_review_table,
    summarize,
)

FIT_CALLS: list[int] = []  # fit が呼ばれたときの行数を記録する（fold ごとに 1 行増える）


class FitCounter(TransformerMixin, BaseEstimator):
    """fit が呼ばれた回数と行数を記録するだけの変換（中身は素通し）。"""

    def fit(self, X, y=None) -> "FitCounter":
        FIT_CALLS.append(len(X))
        return self

    def transform(self, X):
        return X

    def get_feature_names_out(self, input_features=None) -> np.ndarray:
        return np.asarray(input_features, dtype=object)


def counting_pipeline() -> Pipeline:
    """前処理の手前に「fit の回数を数える段」を挟んだ Pipeline。"""
    return Pipeline(
        [
            ("count", FitCounter()),
            ("pre", build_preprocess()),
            ("model", LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)),
        ]
    )


def analyze(df) -> dict[str, object]:
    """2 つの特徴量セットで交差検証し、fit の呼ばれ方も記録する。"""
    rows = {}
    for key, categorical in (("large", CATEGORICAL), ("small", CATEGORICAL_S17)):
        X, y = features_target(df, NUMERIC, categorical)
        scores = cv_auc(build_pipeline(NUMERIC, categorical), X, y)
        mean, std = summarize(scores)
        rows[key] = {
            "categorical": list(categorical),
            "scores": [float(s) for s in scores],
            "mean": mean,
            "std": std,
            "holdout": holdout_auc(df, NUMERIC, categorical),
        }

    FIT_CALLS.clear()
    X, y = features_target(df)
    cv_auc(counting_pipeline(), X, y)  # スコアは上で測ったので、ここでは呼ばれ方だけを見る

    return {
        **rows,
        "mean_gap": rows["small"]["mean"] - rows["large"]["mean"],
        "holdout_gap": rows["large"]["holdout"] - rows["small"]["holdout"],
        "gap_within_std": bool(
            abs(rows["small"]["mean"] - rows["large"]["mean"]) < min(rows["small"]["std"], rows["large"]["std"])
        ),
        "holdout_minus_cv": rows["large"]["holdout"] - rows["large"]["mean"],
        "fit_calls": len(FIT_CALLS),
        "fit_sizes": sorted(set(FIT_CALLS)),
        "n_rows": len(df),
    }


def main() -> None:
    result = analyze(load_review_table())

    print("■ 1. 交差検証（層化 5 分割・shuffle=True・random_state=42）")
    for key, label in (("large", "+ region + channel"), ("small", "category だけ")):
        row = result[key]
        print(f"[{label}] カテゴリ列 {row['categorical']}")
        print(f"  fold ごと       : {fmt_scores(row['scores'])}")
        print(f"  平均 / 標準偏差 : {row['mean']:.4f} / {row['std']:.4f}")
        print(f"  ホールドアウト  : {row['holdout']:.4f}")
    print()

    print("■ 2. 2 つの構成の差")
    print(f"交差検証の平均の差       : {result['mean_gap']:+.4f}")
    print(f"ホールドアウトの差       : {result['holdout_gap']:+.4f}")
    print(f"差が標準偏差より小さいか : {result['gap_within_std']}")
    print(f"ホールドアウト − 平均    : {result['holdout_minus_cv']:+.4f}")
    print()

    print("■ 3. fit は fold ごとに呼ばれている")
    print(f"fit の呼び出し回数       : {result['fit_calls']} 回")
    print(f"1 回あたりの訓練件数     : {result['fit_sizes']}")
    print(f"全体の件数               : {result['n_rows']:,} 件")


if __name__ == "__main__":
    main()
