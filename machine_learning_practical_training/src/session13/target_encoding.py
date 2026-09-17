"""ターゲットエンコーディング（目的変数の平均で置き換える）を、作り方を変えて比べる。

使い方:
    docker compose exec lab python src/session13/target_encoding.py
"""

from __future__ import annotations

import lightgbm

from common import (
    CATEGORY_FEATURE,
    ID_FEATURE,
    RANDOM_STATE,
    auc_of,
    design,
    load_review_features,
    onehot_features,
    scaled_numeric,
    split_features,
    target_features,
    target_means,
)

LEAK_LABEL = "book_id・全データで平均を作る"
CLEAN_LABEL = "book_id・訓練データだけで平均を作る"


def new_gbm() -> lightgbm.LGBMClassifier:
    """比較のたびに新しいモデルを作る（学習済みのモデルを使い回さない）。"""
    return lightgbm.LGBMClassifier(n_estimators=200, random_state=RANDOM_STATE, verbose=-1)


def main() -> None:
    df = load_review_features()
    X_train, X_test, y_train, y_test = split_features(df)
    num_train, num_test = scaled_numeric(X_train, X_test)
    prior = float(y_train.mean())  # 対応表に無い水準を埋める値（訓練データの平均）

    means = target_means(X_train[CATEGORY_FEATURE], y_train)
    print("■ 訓練データのカテゴリ別 高評価率（これがそのまま対応表になる）")
    for name, rate in means.items():
        print(f"{name} : {rate:.4f}")
    print()

    oh_train, oh_test, _ = onehot_features(X_train, X_test)
    te_train, te_test = target_features(X_train, X_test, means, prior, CATEGORY_FEATURE)
    book_means = target_means(X_train[ID_FEATURE], y_train)
    bt_train, bt_test = target_features(X_train, X_test, book_means, prior, ID_FEATURE)
    # 評価データの答えまで使って対応表を作る（やってはいけない作り方）
    leaked_means = target_means(df[ID_FEATURE], df["is_high"])
    bl_train, bl_test = target_features(
        X_train, X_test, leaked_means, float(df["is_high"].mean()), ID_FEATURE
    )

    candidates = [
        ("One-Hot（比較用）", oh_train, oh_test),
        ("category・訓練データだけで平均を作る", te_train, te_test),
        (CLEAN_LABEL, bt_train, bt_test),
        (LEAK_LABEL, bl_train, bl_test),
    ]

    print("■ 同じ LightGBM で、カテゴリの作り方だけを変える")
    scores = {}
    for label, cat_train, cat_test in candidates:
        train, test = design(num_train, cat_train), design(num_test, cat_test)
        scores[label] = auc_of(new_gbm(), train, y_train, test, y_test)
        print(f"{label} | {train.shape[1]} 列 | {scores[label]:.4f}")
    print()

    print("■ 同じ book_id なのに、対応表の作り方で評価が変わる")
    print(f"全データで作った場合       : {scores[LEAK_LABEL]:.4f}")
    print(f"訓練データだけで作った場合 : {scores[CLEAN_LABEL]:.4f}")
    print(f"全データで作ったほうが高く出るか : {bool(scores[LEAK_LABEL] > scores[CLEAN_LABEL])}")
    print("→ 高く出たのは腕が上がったからではありません。評価データの答えを特徴量に混ぜたからです")


if __name__ == "__main__":
    main()
