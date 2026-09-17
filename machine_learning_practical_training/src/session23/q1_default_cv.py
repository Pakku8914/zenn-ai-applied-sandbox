"""問題1: 探索の出発点（探索なしの交差検証）と、探索の見積もりを作る。

実行:
    docker compose exec lab python src/session23/q1_default_cv.py
"""

from __future__ import annotations

from common import (
    build_model,
    cv_auc,
    fit_count,
    fmt_scores,
    load_review_table,
    space_size,
    split_train_test,
    summarize,
)

# これから探そうとしている範囲（まだ探索はしない。数えるだけ）
PLANNED_GRID = {
    "n_estimators": [50, 200],
    "learning_rate": [0.02, 0.05, 0.1],
    "num_leaves": [7, 31],
}


def analyze(df) -> dict[str, object]:
    """既定値の交差検証と、探索計画の学習回数を並べる。"""
    X_train, X_test, y_train, _ = split_train_test(df)
    scores = cv_auc(build_model(), X_train, y_train)
    mean, std = summarize(scores)
    size = space_size(PLANNED_GRID)
    fits = fit_count(PLANNED_GRID)
    return {
        "n_train": len(X_train),
        "n_test": len(X_test),
        "scores": scores,
        "mean": mean,
        "std": std,
        "baseline_fits": len(scores),
        "size": size,
        "fits": fits,
        "times_heavier": fits // len(scores),
    }


def main() -> None:
    df = load_review_table()
    result = analyze(df)

    print("■ 1. 探索なし（既定値）の交差検証")
    print(f"訓練 {result['n_train']} 件 / テスト {result['n_test']} 件（テストは触らない）")
    print(f"fold ごとの ROC AUC : {fmt_scores(result['scores'])}")
    print(f"平均 / 標準偏差     : {result['mean']:.4f} / {result['std']:.4f}")
    print(f"学習した回数        : {result['baseline_fits']} 回")
    print()

    print("■ 2. 探索計画の見積もり")
    for key, values in PLANNED_GRID.items():
        print(f"{key:<16}: {values}（{len(values)} 通り）")
    print(f"組み合わせ数 : {result['size']} 通り")
    print(f"学習回数     : {result['size']} × 5 = {result['fits']} 回")
    print(f"探索なしの   : {result['times_heavier']} 倍の計算量")
    print()

    print("■ 3. なぜ探索を訓練データの中だけで行うのか（説明）")
    print("テストデータのスコアを見て設定を選ぶと、その設定はテストデータに合わせて選ばれたものになり、")
    print("最後に報告するテストのスコアが『初めて見るデータでの成績』ではなくなるからです。")


if __name__ == "__main__":
    main()
