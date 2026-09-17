"""B部（セッション11〜13）で手続き的に書いた前処理を Pipeline に組み替える（本文 3 節）。

手で 4 段書いた場合と Pipeline に載せた場合で、**変換後の行列そのものが一致する**ことを
確認します。結果が変わらないのに Pipeline を使う理由は、この章の 4 節で扱います。

実行:
    docker compose exec lab python src/session25/by_hand_vs_pipeline.py
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


def by_hand(X_train: pd.DataFrame, X_test: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """B部でやったとおりに、前処理を 4 段の手続きとして書く。

    どの段でも「fit は訓練データだけ・評価データは transform だけ」を手で守る必要があります。
    """
    # ① 数値列の欠損を中央値で埋める（セッション11）
    num_imputer = SimpleImputer(strategy="median").set_output(transform="pandas")
    num_imputer.fit(X_train[NUMERIC])
    num_train = num_imputer.transform(X_train[NUMERIC])
    num_test = num_imputer.transform(X_test[NUMERIC])

    # ② 数値列を標準化する（セッション12）
    scaler = StandardScaler().set_output(transform="pandas")
    scaler.fit(num_train)
    num_train = scaler.transform(num_train)
    num_test = scaler.transform(num_test)

    # ③ カテゴリ列の欠損を最頻値で埋める（セッション11）
    cat_imputer = SimpleImputer(strategy="most_frequent").set_output(transform="pandas")
    cat_imputer.fit(X_train[CATEGORICAL])
    cat_train = cat_imputer.transform(X_train[CATEGORICAL])
    cat_test = cat_imputer.transform(X_test[CATEGORICAL])

    # ④ カテゴリ列を 0/1 に開く（セッション13）
    encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=False).set_output(transform="pandas")
    encoder.fit(cat_train)
    oh_train = encoder.transform(cat_train)
    oh_test = encoder.transform(cat_test)

    # ⑤ 横に並べて特徴量の表にする
    return pd.concat([num_train, oh_train], axis=1), pd.concat([num_test, oh_test], axis=1)


def compare(df) -> dict[str, object]:
    """手続き版と Pipeline 版で、変換後の行列と ROC AUC を突き合わせる。"""
    X, y = features_target(df)
    X_train, X_test, y_train, y_test = split(X, y)

    # --- 手続き版 ---
    hand_train, hand_test = by_hand(X_train, X_test)
    hand_model = LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)
    hand_model.fit(hand_train, y_train)
    hand_auc = auc_of(hand_model, hand_test, y_test)

    # --- Pipeline 版（同じ 4 段を 1 つのオブジェクトに載せただけ） ---
    pipeline = build_pipeline().fit(X_train, y_train)
    pipeline_auc = auc_of(pipeline, X_test, y_test)

    pre = build_preprocess().fit(X_train)
    pipe_train = pre.transform(X_train)
    pipe_test = pre.transform(X_test)

    return {
        "hand_shape": hand_train.shape,
        "pipe_shape": pipe_train.shape,
        "same_train": bool(np.allclose(hand_train.to_numpy(dtype="float64"), pipe_train)),
        "same_test": bool(np.allclose(hand_test.to_numpy(dtype="float64"), pipe_test)),
        "hand_auc": hand_auc,
        "pipeline_auc": pipeline_auc,
        "auc_gap": hand_auc - pipeline_auc,
        "hand_columns": [str(name) for name in hand_train.columns],
        "pipe_columns": [str(name) for name in pre.get_feature_names_out()],
    }


def main() -> None:
    result = compare(load_review_table())

    print("■ 1. 変換後の形")
    print(f"手続き版   : {result['hand_shape']}")
    print(f"Pipeline版 : {result['pipe_shape']}")
    print()

    print("■ 2. 中身が一致するか")
    print(f"訓練データの行列が一致   : {result['same_train']}")
    print(f"評価データの行列が一致   : {result['same_test']}")
    print()

    print("■ 3. ROC AUC")
    print(f"手続き版   : {result['hand_auc']:.4f}")
    print(f"Pipeline版 : {result['pipeline_auc']:.4f}")
    print(f"差         : {result['auc_gap']:+.6f}")
    print()

    print("■ 4. 列名（先頭 6 列）")
    print(f"手続き版   : {result['hand_columns'][:6]}")
    print(f"Pipeline版 : {result['pipe_columns'][:6]}")


if __name__ == "__main__":
    main()
