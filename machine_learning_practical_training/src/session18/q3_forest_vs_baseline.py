"""問題3 の解答: ランダムフォレストを学習し、ベースラインと線形モデルに並べて報告する。

使い方:
    docker compose exec lab python src/session18/q3_forest_vs_baseline.py
"""

from __future__ import annotations

from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from common import (
    MAX_ITER,
    N_ESTIMATORS,
    N_JOBS,
    RANDOM_STATE,
    TARGET,
    baseline_scores,
    feature_names,
    fit_and_evaluate,
    load_review_table,
    pad,
    split_xy,
)


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_xy(df)

    forest_pipeline, forest = fit_and_evaluate(
        # 引数は 3 つとも明示する（既定値に任せると結果が再現できなくなる）
        RandomForestClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, n_jobs=N_JOBS),
        X_train,
        y_train,
        X_test,
        y_test,
    )
    _, logistic = fit_and_evaluate(
        LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE),
        X_train,
        y_train,
        X_test,
        y_test,
    )
    base = baseline_scores(y_test)

    print("■ 問題3: ランダムフォレストをベースラインと並べる")
    print(
        f"訓練 {len(X_train):,} 件 / 評価 {len(X_test):,} 件 / "
        f"特徴量 {len(feature_names(forest_pipeline))} 列 / 正例率 {df[TARGET].mean():.4f}"
    )
    print()

    rows = [
        ("ベースライン（全部 高評価）", base),
        (f"ランダムフォレスト（{N_ESTIMATORS} 本）", forest),
        ("ロジスティック回帰", logistic),
    ]
    print(f"{pad('モデル', 30)}| accuracy | ROC AUC")
    for label, scores in rows:
        print(f"{pad(label, 30)}|  {scores['accuracy']:.4f}  | {scores['roc_auc']:.4f}")
    print()

    print("■ 差（フォレストから見た差）")
    print(f"ベースラインとの accuracy の差       : {forest['accuracy'] - base['accuracy']:+.4f}")
    print(f"ベースラインとの ROC AUC の差        : {forest['roc_auc'] - base['roc_auc']:+.4f}")
    print(f"ロジスティック回帰との accuracy の差 : {forest['accuracy'] - logistic['accuracy']:+.4f}")
    print(f"ロジスティック回帰との ROC AUC の差  : {forest['roc_auc'] - logistic['roc_auc']:+.4f}")
    print()

    print("■ 判定")
    print(f"accuracy でベースラインを超えたか            : {forest['accuracy'] > base['accuracy']}")
    print(f"ROC AUC でベースラインを超えたか             : {forest['roc_auc'] > base['roc_auc']}")
    print(f"ROC AUC でロジスティック回帰を超えたか       : {forest['roc_auc'] > logistic['roc_auc']}")
    print()

    print("■ 報告（2 文）")
    print("ランダムフォレストは順位付け（ROC AUC）ではベースラインを大きく上回りますが、")
    print("閾値 0.5 での accuracy は多数クラスをそのまま答えるベースラインに届きません。")


if __name__ == "__main__":
    main()
