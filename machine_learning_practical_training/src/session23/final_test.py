"""探索で決めた 1 つの設定を、テストデータで 1 回だけ測る（本文 6 節・8 節）。

このスクリプトだけがテストデータに触ります。**探索のスクリプトからは触りません。**
比較のため、セッション17 のロジスティック回帰も同じ分割で測り直します。

実行:
    docker compose exec lab python src/session23/final_test.py
"""

from __future__ import annotations

from common import (
    build_linear_model,
    build_model,
    load_review_table,
    split_train_test,
    test_auc,
)
from default_baseline import baseline
from grid_search import search as run_grid_search

# 探索（グリッドサーチ）が選んだ設定。テストの前に「これで確定」と決め打つ
CHOSEN_PARAMS = {"learning_rate": 0.05, "n_estimators": 200, "num_leaves": 7}


def final(df, params: dict | None = None) -> dict[str, object]:
    """決めた設定で訓練データ全体を学習し、テストデータで 1 回だけ測る。"""
    params = CHOSEN_PARAMS if params is None else params
    X_train, X_test, y_train, y_test = split_train_test(df)
    tuned = build_model(**params).fit(X_train, y_train)
    linear = build_linear_model().fit(X_train, y_train)
    tuned_auc = test_auc(tuned, X_test, y_test)
    linear_auc = test_auc(linear, X_test, y_test)
    return {
        "params": params,
        "n_test": len(X_test),
        "tuned_test": tuned_auc,
        "linear_test": linear_auc,
        "gap_to_linear": tuned_auc - linear_auc,
        "linear_wins": linear_auc > tuned_auc,
    }


def main() -> None:
    df = load_review_table()
    grid_result = run_grid_search(df)
    baseline_result = baseline(df)
    result = final(df, grid_result["best_params"])

    print("■ 探索で選んだ設定（テストの前に確定させる）")
    print(f"{result['params']}")
    print()

    print("■ 交差検証（訓練データの中）とテストデータ 1 回の対比")
    print(f"探索なしの CV         : {baseline_result['mean']:.4f}")
    print(f"探索後の CV           : {grid_result['best_cv']:.4f}")
    print(f"探索後のテスト        : {result['tuned_test']:.4f}（{result['n_test']} 件・ここで初めて使った）")
    print()

    print("■ ロジスティック回帰（セッション17）との比較")
    print(f"ロジスティック回帰のテスト : {result['linear_test']:.4f}")
    print(f"LightGBM（探索後）− 線形   : {result['gap_to_linear']:.4f}")
    print(f"線形モデルの勝ち           : {result['linear_wins']}")
    print()
    print("探索はモデル選択の代わりにはなりません。探索しても線形モデルに届きませんでした。")


if __name__ == "__main__":
    main()
