"""問題4 の解答: スケーリング 3 通り × モデル 2 種類の ROC AUC を、基準線と並べて比べる。

使い方:
    docker compose exec lab python src/session12/q4_scaling_auc.py
"""

from __future__ import annotations

import lightgbm
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

from common import (
    RANDOM_STATE,
    TEST_SIZE,
    load_review_features,
    make_design_matrix,
    scale_numeric,
)

SCALERS = ["none", "standard", "minmax"]
LABELS = {"none": "スケーリングなし", "standard": "StandardScaler", "minmax": "MinMaxScaler"}


def main() -> None:
    df = load_review_features()
    X, y = make_design_matrix(df), df["is_high"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    print(f"訓練 {len(X_train):,} 件 / 評価 {len(X_test):,} 件 / 正例率 {y.mean():.4f}")

    # 基準線: 全員を同じ確率で「高評価」と予測するモデル。順位が付かないので AUC は 0.5 になる
    baseline = roc_auc_score(y_test, np.full(len(y_test), 0.9))
    print(f"基準線（全員を高評価と予測）の ROC AUC : {baseline:.4f}")
    print()

    results: dict[str, dict[str, float]] = {"ロジスティック回帰": {}, "LightGBM": {}}
    for name in SCALERS:
        train, test = scale_numeric(X_train, X_test, name)
        lr = LogisticRegression(max_iter=1000, random_state=RANDOM_STATE).fit(train, y_train)
        gbm = lightgbm.LGBMClassifier(
            n_estimators=200, random_state=RANDOM_STATE, verbose=-1
        ).fit(train, y_train)
        results["ロジスティック回帰"][name] = float(roc_auc_score(y_test, lr.predict_proba(test)[:, 1]))
        results["LightGBM"][name] = float(roc_auc_score(y_test, gbm.predict_proba(test)[:, 1]))

    print("モデル | " + " | ".join(LABELS[name] for name in SCALERS))
    for model_name, aucs in results.items():
        print(f"{model_name} | " + " | ".join(f"{aucs[name]:.4f}" for name in SCALERS))
    print()

    print("■ スケーリングで AUC はどれだけ動いたか")
    for model_name, aucs in results.items():
        spread = max(aucs.values()) - min(aucs.values())
        best = max(aucs, key=lambda name: aucs[name])
        print(f"{model_name} : 最良は {LABELS[best]} / 差の幅が 0.005 未満か {bool(spread < 0.005)}")
    print()
    print("結論: スケーリングは AUC をほとんど動かさない（本書の許容誤差 0.005 の範囲）。")
    print("      木モデルは分割の境目が動くぶんだけ差が出るが、方向は保証されない。")
    print("      線形モデルでスケーリングするのは、精度のためではなく収束と係数の解釈のため。")


if __name__ == "__main__":
    main()
