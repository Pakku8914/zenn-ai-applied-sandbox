"""問題3 の解答: B部で手続き的に書いた前処理と Pipeline の結果を突き合わせる。

実行:
    docker compose exec lab python src/session25/q3_hand_vs_pipeline.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from common import (
    CATEGORICAL,
    MAX_ITER,
    NUMERIC,
    RANDOM_STATE,
    auc_of,
    build_pipeline,
    build_preprocess,
    features_target,
    load_review_table,
    split,
)


def hand_design(X_train: pd.DataFrame, X_test: pd.DataFrame) -> dict[str, object]:
    """セッション11〜13 の手順を、そのまま 4 段の手続きとして書く。

    fit に渡すのは訓練データだけ。評価データには transform しか当てない。
    この「だけ」を 4 回とも自分で守る必要があるのが、手続き版の弱点です。
    """
    stages: list[tuple[str, tuple[int, int]]] = []

    # ① 数値列の欠損を中央値で埋める（セッション11）
    num_imputer = SimpleImputer(strategy="median").set_output(transform="pandas").fit(X_train[NUMERIC])
    num_train = num_imputer.transform(X_train[NUMERIC])
    num_test = num_imputer.transform(X_test[NUMERIC])
    stages.append(("① 欠損補完（数値）", num_train.shape))

    # ② 数値列を標準化する（セッション12）
    scaler = StandardScaler().set_output(transform="pandas").fit(num_train)
    num_train, num_test = scaler.transform(num_train), scaler.transform(num_test)
    stages.append(("② 標準化", num_train.shape))

    # ③ カテゴリ列の欠損を最頻値で埋める（セッション11）
    cat_imputer = (
        SimpleImputer(strategy="most_frequent").set_output(transform="pandas").fit(X_train[CATEGORICAL])
    )
    cat_train = cat_imputer.transform(X_train[CATEGORICAL])
    cat_test = cat_imputer.transform(X_test[CATEGORICAL])
    stages.append(("③ 欠損補完（カテゴリ）", cat_train.shape))

    # ④ カテゴリ列を 0/1 に開く（セッション13）
    encoder = (
        OneHotEncoder(handle_unknown="ignore", sparse_output=False)
        .set_output(transform="pandas")
        .fit(cat_train)
    )
    oh_train, oh_test = encoder.transform(cat_train), encoder.transform(cat_test)
    stages.append(("④ One-Hot", oh_train.shape))

    return {
        "stages": stages,
        "train": pd.concat([num_train, oh_train], axis=1),
        "test": pd.concat([num_test, oh_test], axis=1),
    }


def analyze(df) -> dict[str, object]:
    """手続き版と Pipeline 版で、行列と ROC AUC が一致するかを確かめる。"""
    X, y = features_target(df)
    X_train, X_test, y_train, y_test = split(X, y)

    hand = hand_design(X_train, X_test)
    hand_model = LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)
    hand_model.fit(hand["train"], y_train)
    hand_auc = auc_of(hand_model, hand["test"], y_test)

    pipeline = build_pipeline().fit(X_train, y_train)
    pipeline_auc = auc_of(pipeline, X_test, y_test)
    pre = build_preprocess().fit(X_train)
    pipe_train, pipe_test = pre.transform(X_train), pre.transform(X_test)

    return {
        "stages": [(label, tuple(int(v) for v in shape)) for label, shape in hand["stages"]],
        "hand_shape": tuple(int(v) for v in hand["train"].shape),
        "pipe_shape": tuple(int(v) for v in pipe_train.shape),
        "same_train": bool(np.allclose(hand["train"].to_numpy(dtype="float64"), pipe_train)),
        "same_test": bool(np.allclose(hand["test"].to_numpy(dtype="float64"), pipe_test)),
        "hand_auc": hand_auc,
        "pipeline_auc": pipeline_auc,
        "auc_gap": hand_auc - pipeline_auc,
        "hand_first_columns": [str(c) for c in hand["train"].columns[:5]],
        "pipe_first_columns": [str(c) for c in pre.get_feature_names_out()[:5]],
    }


def main() -> None:
    result = analyze(load_review_table())

    print("■ 1. 手続き版の各段の形")
    for label, shape in result["stages"]:
        print(f"  {label:<22}: {shape}")
    print()

    print("■ 2. つなげた結果")
    print(f"手続き版の形     : {result['hand_shape']}")
    print(f"Pipeline 版の形  : {result['pipe_shape']}")
    print(f"訓練データが一致 : {result['same_train']}")
    print(f"評価データが一致 : {result['same_test']}")
    print()

    print("■ 3. ROC AUC")
    print(f"手続き版   : {result['hand_auc']:.4f}")
    print(f"Pipeline版 : {result['pipeline_auc']:.4f}")
    print(f"差         : {result['auc_gap']:+.6f}")
    print()

    print("■ 4. 列名の違い（中身は同じ）")
    print(f"手続き版   : {result['hand_first_columns']}")
    print(f"Pipeline版 : {result['pipe_first_columns']}")


if __name__ == "__main__":
    main()
