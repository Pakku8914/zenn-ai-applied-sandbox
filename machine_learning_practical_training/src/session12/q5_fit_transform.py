"""問題5 の解答: fit の対象を間違えると何が変わるのかを、数値と予測で確かめる。

使い方:
    docker compose exec lab python src/session12/q5_fit_transform.py
"""

from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MinMaxScaler, StandardScaler

from common import (
    NUMERIC_FEATURES,
    RANDOM_STATE,
    TEST_SIZE,
    load_review_features,
    make_design_matrix,
)


def shown(values: np.ndarray) -> list[float]:
    return [round(float(v), 4) for v in np.ravel(values)]


def main() -> None:
    train = np.array([[100.0], [200.0], [300.0]])
    test = np.array([[400.0]])

    print("■ おもちゃのデータ（訓練 100/200/300・検証 400）")
    scaler = StandardScaler().fit(train)
    print(f"訓練で fit → 検証を transform : {shown(scaler.transform(test))}")
    print(f"検証に fit_transform          : {shown(StandardScaler().fit_transform(test))}")
    print(f"MinMaxScaler で transform     : {shown(MinMaxScaler().fit(train).transform(test))}")
    print("→ 同じ 400 が、手順によって 2.4495 にも 0.0 にもなる")
    print("→ MinMaxScaler の出力が 0〜1 に収まるのは訓練データだけ")
    print()

    df = load_review_features()
    X, y = make_design_matrix(df), df["is_high"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )

    # 正しい手順: 訓練データだけで fit する
    correct = StandardScaler().fit(X_train[NUMERIC_FEATURES])
    # 間違った手順: 検証データも含めた全データで fit する（検証データを覗いている）
    leaked = StandardScaler().fit(X[NUMERIC_FEATURES])

    def prepare(scaler: StandardScaler) -> tuple[np.ndarray, np.ndarray]:
        tr, te = X_train.copy(), X_test.copy()
        tr[NUMERIC_FEATURES] = scaler.transform(X_train[NUMERIC_FEATURES])
        te[NUMERIC_FEATURES] = scaler.transform(X_test[NUMERIC_FEATURES])
        return tr, te

    probabilities = {}
    for label, scaler in [("正しい手順", correct), ("全データで fit", leaked)]:
        tr, te = prepare(scaler)
        model = LogisticRegression(max_iter=1000, random_state=RANDOM_STATE).fit(tr, y_train)
        probabilities[label] = model.predict_proba(te)[:, 1]

    auc_correct = roc_auc_score(y_test, probabilities["正しい手順"])
    auc_leaked = roc_auc_score(y_test, probabilities["全データで fit"])
    print("■ 実データ（高評価レビューの分類）")
    print(f"正しい手順の ROC AUC       : {auc_correct:.4f}")
    print(f"予測確率が完全に一致するか : "
          f"{bool(np.array_equal(probabilities['正しい手順'], probabilities['全データで fit']))}")
    print(f"AUC の差が 0.005 未満か    : {bool(abs(auc_correct - auc_leaked) < 0.005)}")
    print("→ 数字がほとんど変わらないから気づけない。だから手順で防ぐ（セッション22で再訪します）")


if __name__ == "__main__":
    main()
