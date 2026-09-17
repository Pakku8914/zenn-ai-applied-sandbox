"""問題6 の解答: FunctionTransformer で log1p の枝を足す。

実行:
    docker compose exec lab python src/session25/q6_log_transform.py
"""

from __future__ import annotations

import numpy as np
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
    build_pipeline,
    categorical_steps,
    features_target,
    load_review_table,
    numeric_steps,
    split,
)

LOG_COLUMNS = ["unit_price", "body_length"]                   # 右に長く裾を引く 2 列
PLAIN_COLUMNS = [c for c in NUMERIC if c not in LOG_COLUMNS]  # 残りの 2 列


def log_steps() -> Pipeline:
    """欠損を埋めてから log1p を通し、最後に標準化する枝。"""
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("log", FunctionTransformer(np.log1p, feature_names_out="one-to-one")),
            ("scale", StandardScaler()),
        ]
    )


def log_pipeline() -> Pipeline:
    """log1p を通す枝・そのままの枝・カテゴリの枝の 3 本立てにする。"""
    preprocess = ColumnTransformer(
        [
            ("log", log_steps(), LOG_COLUMNS),
            ("num", numeric_steps(), PLAIN_COLUMNS),
            ("cat", categorical_steps(), CATEGORICAL),
        ]
    )
    return Pipeline(
        [
            ("pre", preprocess),
            ("model", LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)),
        ]
    )


def analyze(df) -> dict[str, object]:
    """log1p を挟んだ Pipeline と、挟まない Pipeline を同じ分割で比べる。"""
    X, y = features_target(df)
    X_train, X_test, y_train, y_test = split(X, y)

    plain = build_pipeline().fit(X_train, y_train)
    logged = log_pipeline().fit(X_train, y_train)

    pre = logged.named_steps["pre"]
    names = [str(name) for name in pre.get_feature_names_out()]

    # log1p が本当に当たっているかを手計算で確かめる
    branch = pre.named_transformers_["log"]
    manual = np.log1p(X_train[LOG_COLUMNS].to_numpy(dtype="float64"))
    scaled = (manual - manual.mean(axis=0)) / manual.std(axis=0)
    matches = bool(np.allclose(branch.transform(X_train[LOG_COLUMNS]), scaled))

    plain_auc = auc_of(plain, X_test, y_test)
    log_auc = auc_of(logged, X_test, y_test)
    return {
        "names": names,
        "n_names": len(names),
        "log_names": [name for name in names if name.startswith("log__")],
        "num_names": [name for name in names if name.startswith("num__")],
        "n_cat_names": sum(1 for name in names if name.startswith("cat__")),
        "matches_manual": matches,
        "plain_auc": plain_auc,
        "log_auc": log_auc,
        "gap": log_auc - plain_auc,
        "log_beats_chance": bool(log_auc > 0.5),
    }


def main() -> None:
    result = analyze(load_review_table())

    print("■ 1. 変換後の列")
    print(f"列の合計       : {result['n_names']} 列")
    print(f"log__ の列     : {result['log_names']}")
    print(f"num__ の列     : {result['num_names']}")
    print(f"cat__ の列の数 : {result['n_cat_names']} 列")
    print(f"中身が np.log1p と一致 : {result['matches_manual']}")
    print()

    print("■ 2. ROC AUC")
    print(f"log1p なし : {result['plain_auc']:.4f}")
    print(f"log1p あり : {result['log_auc']:.4f}")
    print(f"差         : {result['gap']:+.4f}")


if __name__ == "__main__":
    main()
