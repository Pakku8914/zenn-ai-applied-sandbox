"""高評価レビューの分類をロジスティック回帰で学習し、ベースラインと比べる。

使い方:
    docker compose exec lab python src/session17/fit_logistic.py
"""

from __future__ import annotations

from common import (
    DEFAULT_THRESHOLD,
    MAX_ITER,
    RANDOM_STATE,
    TEST_SIZE,
    baseline_scores,
    basic_scores,
    fit_model,
    load_review_table,
    prepare,
    split_xy,
)


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    model = fit_model(train, y_train)

    print("■ 高評価レビュー（星 4 以上）を当てる分類")
    print(f"母集団 {len(df):,} 行 / 訓練 {len(X_train):,} 件 / 評価 {len(X_test):,} 件 / 正例率 {df['is_high'].mean():.4f}")
    print(f"分割の条件 test_size={TEST_SIZE} / random_state={RANDOM_STATE} / 層化あり")
    print(f"前処理後の特徴量 {train.shape[1]} 列: {', '.join(names)}")
    print(f"反復回数が上限 {MAX_ITER} に達したか: {int(model.n_iter_[0]) >= MAX_ITER}")
    print()

    proba_matrix = model.predict_proba(test)
    scores = basic_scores(y_test, proba_matrix)
    print(f"■ ロジスティック回帰（閾値 {DEFAULT_THRESHOLD}）")
    print(f"accuracy {scores['accuracy']:.4f} / ROC AUC {scores['roc_auc']:.4f} / 対数損失 {scores['log_loss']:.4f}")
    print()

    base = baseline_scores(y_test)
    print("■ ベースライン（何も学習せず「全部 高評価」と答える）")
    print(f"accuracy {base['accuracy']:.4f} / ROC AUC {base['roc_auc']:.4f}")
    print(f"accuracy の改善 {scores['accuracy'] - base['accuracy']:+.4f}")
    print("→ accuracy はほとんど変わらないのに、ROC AUC は 0.5 から大きく動いた点に注目してください。")


if __name__ == "__main__":
    main()
