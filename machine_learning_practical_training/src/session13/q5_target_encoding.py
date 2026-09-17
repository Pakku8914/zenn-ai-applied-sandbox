"""問題5 の解答: ターゲットエンコーディングを 3 通り作り、リークの大きさを測る。

使い方:
    docker compose exec lab python src/session13/q5_target_encoding.py
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

TOLERANCE = 0.005  # 本書の許容誤差
ONEHOT = "One-Hot（比較用）"
CATEGORY_CLEAN = "category・訓練データだけ"
BOOK_CLEAN = "book_id・訓練データだけ"
BOOK_LEAK = "book_id・全データ"


def new_gbm() -> lightgbm.LGBMClassifier:
    return lightgbm.LGBMClassifier(n_estimators=200, random_state=RANDOM_STATE, verbose=-1)


def main() -> None:
    df = load_review_features()
    X_train, X_test, y_train, y_test = split_features(df)
    num_train, num_test = scaled_numeric(X_train, X_test)
    prior = float(y_train.mean())

    print("■ 1 水準あたりの訓練データの行数（少ないほど平均が当てにならない）")
    for column in (CATEGORY_FEATURE, ID_FEATURE):
        print(f"{column:<8} : 水準 {X_train[column].nunique()} / 1 水準あたり {len(X_train) / X_train[column].nunique():.1f} 行")
    print()

    means = target_means(X_train[CATEGORY_FEATURE], y_train)
    print("■ 訓練データで作った対応表（category）")
    for name, rate in means.items():
        print(f"{name} : {rate:.4f}")
    print()

    oh_train, oh_test, _ = onehot_features(X_train, X_test)
    cat_train, cat_test = target_features(X_train, X_test, means, prior, CATEGORY_FEATURE)
    book_means = target_means(X_train[ID_FEATURE], y_train)
    bt_train, bt_test = target_features(X_train, X_test, book_means, prior, ID_FEATURE)
    leaked_means = target_means(df[ID_FEATURE], df["is_high"])  # 評価データの答えも使ってしまう
    bl_train, bl_test = target_features(
        X_train, X_test, leaked_means, float(df["is_high"].mean()), ID_FEATURE
    )

    print("■ ROC AUC（モデルは LightGBM・他の条件はすべて同じ）")
    scores = {}
    for label, cat_tr, cat_te in [
        (ONEHOT, oh_train, oh_test),
        (CATEGORY_CLEAN, cat_train, cat_test),
        (BOOK_CLEAN, bt_train, bt_test),
        (BOOK_LEAK, bl_train, bl_test),
    ]:
        train, test = design(num_train, cat_tr), design(num_test, cat_te)
        scores[label] = auc_of(new_gbm(), train, y_train, test, y_test)
        print(f"{label} | {train.shape[1]} 列 | {scores[label]:.4f}")
    print()

    print("■ 判定")
    print(f"全データで作ったほうが高く出るか : {bool(scores[BOOK_LEAK] > scores[BOOK_CLEAN])}")
    print(f"book_id を訓練データだけで作ると One-Hot より下がるか : {bool(scores[BOOK_CLEAN] < scores[ONEHOT])}")
    print(
        f"category を訓練データだけで作ると One-Hot との差が {TOLERANCE} 未満か : "
        f"{bool(abs(scores[CATEGORY_CLEAN] - scores[ONEHOT]) < TOLERANCE)}"
    )
    print()

    print("■ 結論")
    print("book_id の対応表を全データで作ると、評価データの答えが特徴量に入り込みます。")
    print("本番では未来の答えが手に入らないので、この評価は再現できません（見かけの改善）。")
    print("訓練データだけで作っても、book_id は 1 水準あたりの行数が少なく、平均が不安定になります。")


if __name__ == "__main__":
    main()
