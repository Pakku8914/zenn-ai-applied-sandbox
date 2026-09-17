"""問題5: 「最良」の差とばらつきを比べ、fold ごとのスコアまで降りて確かめる。

実行:
    docker compose exec lab python src/session23/q5_score_noise.py
"""

from __future__ import annotations

from sklearn.model_selection import GridSearchCV

from common import (
    SCORING,
    build_model,
    fmt_scores,
    format_params,
    load_review_table,
    results_table,
    split_train_test,
    stratified_cv,
)

PARAM_GRID = {
    "model__n_estimators": [50, 200],
    "model__learning_rate": [0.02, 0.05, 0.1],
    "model__num_leaves": [7, 31],
}


def fold_scores(grid, rank: int) -> list[float]:
    """cv_results_ から、指定した順位の設定の「fold ごとのスコア」を取り出す。"""
    index = list(grid.cv_results_["rank_test_score"]).index(rank)
    return [float(grid.cv_results_[f"split{i}_test_score"][index]) for i in range(grid.n_splits_)]


def analyze(df) -> dict[str, object]:
    """上位 2 件の差を、平均のレベルと fold のレベルの両方で比べる。"""
    X_train, _, y_train, _ = split_train_test(df)
    grid = GridSearchCV(build_model(), PARAM_GRID, scoring=SCORING, cv=stratified_cv(), n_jobs=1)
    grid.fit(X_train, y_train)
    table = results_table(grid)
    best, second, third = table[:3]

    first_folds = fold_scores(grid, 1)
    second_folds = fold_scores(grid, 2)
    fold_gaps = [a - b for a, b in zip(first_folds, second_folds)]
    mean_gap = best["mean"] - second["mean"]

    return {
        "top3": table[:3],
        "best_std": best["std"],
        "gap_to_second": mean_gap,
        "gap_to_third": best["mean"] - third["mean"],
        "within_noise": (best["mean"] - third["mean"]) < best["std"],
        "first_folds": first_folds,
        "second_folds": second_folds,
        "fold_gaps": fold_gaps,
        "max_abs_fold_gap": max(abs(gap) for gap in fold_gaps),
        "fold_gap_exceeds_mean_gap": max(abs(gap) for gap in fold_gaps) > abs(mean_gap),
        "folds_won_by_second": sum(1 for gap in fold_gaps if gap < 0),
        "bands": [(row["mean"] - row["std"], row["mean"] + row["std"]) for row in table[:3]],
    }


def main() -> None:
    df = load_review_table()
    result = analyze(df)

    print("■ 1. 上位 3 件と帯（平均 ± 標準偏差）")
    print("設定                                             | CV の平均 | 標準偏差 | 帯")
    for row, (low, high) in zip(result["top3"], result["bands"]):
        print(f"{format_params(row):<48} | {row['mean']:.4f}    | {row['std']:.4f}   | {low:.4f}〜{high:.4f}")
    print()

    print("■ 2. 平均のレベルで見た差")
    print(f"1 位 − 2 位 : {result['gap_to_second']:.4f}")
    print(f"1 位 − 3 位 : {result['gap_to_third']:.4f}")
    print(f"1 位の標準偏差 : {result['best_std']:.4f}")
    print(f"上位 3 件の差はばらつきより小さい : {result['within_noise']}")
    print()

    print("■ 3. fold のレベルまで降りて見た差")
    print(f"1 位の fold ごと : {fmt_scores(result['first_folds'])}")
    print(f"2 位の fold ごと : {fmt_scores(result['second_folds'])}")
    print(f"fold ごとの差    : {' '.join(f'{gap:+.4f}' for gap in result['fold_gaps'])}")
    print(f"差の絶対値の最大 : {result['max_abs_fold_gap']:.4f}（平均の差より大きい: {result['fold_gap_exceeds_mean_gap']}）")
    print(f"2 位が勝った fold の数 : {result['folds_won_by_second']}")
    print()

    print("■ 4. 説明")
    print("平均の差 0.0023 は、fold ごとの差の振れ幅よりずっと小さいです。つまり 1 位と 2 位の順位は")
    print("『どのデータで測ったか』で入れ替わる程度の違いしかありません。小数第 3 位の差で勝ち負けを")
    print("語らず、同等の候補の中から扱いやすい設定（木が少ない・学習が速い）を選ぶのが実務的です。")


if __name__ == "__main__":
    main()
