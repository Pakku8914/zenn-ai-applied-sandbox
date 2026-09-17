"""LightGBM を既定のパラメータで学習し、ベースラインとロジスティック回帰と並べて報告する。

使い方:
    docker compose exec lab python src/session19/fit_lightgbm.py
"""

from __future__ import annotations

from sklearn.linear_model import LogisticRegression

from common import (
    LEARNING_RATE,
    N_ESTIMATORS,
    NUM_LEAVES,
    RANDOM_STATE,
    baseline_scores,
    fit_and_score,
    load_review_table,
    make_lgbm,
    prepare,
    print_scores,
    split_xy,
)

MAX_ITER = 1000  # ロジスティック回帰の反復上限（セッション17 と同じ条件）


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    print(f"訓練 {len(X_train):,} 件 / 評価 {len(X_test):,} 件 / 特徴量 {train.shape[1]} 列")
    print(f"正例率（高評価の割合）: {df['is_high'].mean():.4f}")
    print()

    # LightGBM。random_state と verbose=-1 は必ず指定する（再現性のため・ログで埋まるのを防ぐため）
    model, scores = fit_and_score(
        make_lgbm(n_estimators=N_ESTIMATORS, learning_rate=LEARNING_RATE, num_leaves=NUM_LEAVES),
        train,
        y_train,
        test,
        y_test,
    )

    print("■ 同じ分割・同じ特徴量での比較")
    print_scores("ベースライン（全部 高評価）", baseline_scores(y_test))
    _, linear = fit_and_score(
        LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE), train, y_train, test, y_test
    )
    print_scores("ロジスティック回帰", linear)
    print_scores(f"LightGBM（{N_ESTIMATORS} 本・既定）", scores)
    print()

    print("■ 学習したモデルの中身")
    print(f"木の本数: {model.booster_.num_trees()} 本")
    print(f"学習率: {model.get_params()['learning_rate']}")
    print(f"葉の数の上限: {model.get_params()['num_leaves']}")
    print()
    print("判断: ベースラインより ROC AUC は大きく上がりましたが、ロジスティック回帰には届きません。")
    print("      パラメータを既定のまま使っている点を、次の節で疑ってみます。")


if __name__ == "__main__":
    main()
