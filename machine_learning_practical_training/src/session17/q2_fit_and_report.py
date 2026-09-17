"""問題2 の解答: 高評価レビューの分類を学習し、ベースラインと並べて報告する。

使い方:
    docker compose exec lab python src/session17/q2_fit_and_report.py
"""

from __future__ import annotations

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss, roc_auc_score
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from common import (
    CATEGORICAL,
    MAX_ITER,
    NUMERIC,
    RANDOM_STATE,
    load_review_table,
    split_xy,
)


def build_matrices(X_train, X_test):
    """前処理を自分で組み立てる。fit は訓練データだけに掛ける（セッション12 の約束）。"""
    pre = ColumnTransformer(
        [
            ("num", StandardScaler(), NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
        ]
    )
    return pre, pre.fit_transform(X_train), pre.transform(X_test)


def report(df) -> dict[str, float]:
    """学習して、本文に載せた 3 つの指標とベースラインを 1 つの辞書にまとめる。"""
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test = build_matrices(X_train, X_test)
    model = LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE).fit(train, y_train)

    proba_matrix = model.predict_proba(test)
    proba = proba_matrix[:, 1]
    always_one = np.ones(len(y_test), dtype="int64")
    return {
        "n_train": len(X_train),
        "n_test": len(X_test),
        "n_features": train.shape[1],
        "positive_rate": float(df["is_high"].mean()),
        "accuracy": float(accuracy_score(y_test, model.predict(test))),
        "roc_auc": float(roc_auc_score(y_test, proba)),
        "log_loss": float(log_loss(y_test, proba_matrix)),
        "baseline_accuracy": float(accuracy_score(y_test, always_one)),
        "baseline_roc_auc": float(roc_auc_score(y_test, np.full(len(y_test), 0.5))),
    }


def main() -> None:
    result = report(load_review_table())
    print("■ 学習の条件")
    print(f"訓練 {result['n_train']:,} 件 / 評価 {result['n_test']:,} 件 / 特徴量 {result['n_features']} 列"
          f" / 正例率 {result['positive_rate']:.4f}")
    print()
    print("■ ロジスティック回帰")
    print(f"accuracy {result['accuracy']:.4f} / ROC AUC {result['roc_auc']:.4f} / 対数損失 {result['log_loss']:.4f}")
    print()
    print("■ ベースライン（全部 高評価）")
    print(f"accuracy {result['baseline_accuracy']:.4f} / ROC AUC {result['baseline_roc_auc']:.4f}")
    print()
    gain = result["accuracy"] - result["baseline_accuracy"]
    print(f"accuracy の改善 {gain:+.4f} / ROC AUC の改善 {result['roc_auc'] - result['baseline_roc_auc']:+.4f}")
    print("判断: accuracy はベースラインをわずかに上回っただけなので、accuracy だけでは学習できたと言えません。")
    print("      一方 ROC AUC は 0.5（当て推量）から大きく離れているので、順位付けの力は身についています。")


if __name__ == "__main__":
    main()
