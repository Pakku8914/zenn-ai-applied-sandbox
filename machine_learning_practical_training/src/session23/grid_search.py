"""グリッドサーチ（総当たり）を交差検証と組み合わせて回す（本文 2 節）。

**テストデータには触りません。** 探索は訓練データの中だけで行います。

実行:
    docker compose exec lab python src/session23/grid_search.py
"""

from __future__ import annotations

from sklearn.model_selection import GridSearchCV

from common import (
    OUT_DIR,
    SCORING,
    build_model,
    fit_count,
    fmt_scores,
    format_params,
    load_review_table,
    results_table,
    save_figure,
    space_size,
    split_train_test,
    stratified_cv,
    strip_prefix,
)

FIGURE_NAME = "s23_grid_scores.png"

# 探索する範囲。learning_rate は等比（0.02 → 0.05 → 0.1）で並べる
PARAM_GRID = {
    "model__n_estimators": [50, 200],
    "model__learning_rate": [0.02, 0.05, 0.1],
    "model__num_leaves": [7, 31],
}


def search(df) -> dict[str, object]:
    """12 通りを層化 5 分割で総当たりし、結果を表にして返す。"""
    X_train, _, y_train, _ = split_train_test(df)
    grid = GridSearchCV(
        build_model(),
        PARAM_GRID,
        scoring=SCORING,
        cv=stratified_cv(),
        n_jobs=1,  # 再現性のため 1 本で回す
        refit=True,  # 探索が終わったら最良の設定で訓練データ全体を学習し直す
    )
    grid.fit(X_train, y_train)
    table = results_table(grid)
    return {
        "grid": grid,
        "table": table,
        "n_combinations": space_size(PARAM_GRID),
        "n_fits": fit_count(PARAM_GRID),
        "actual_fits": len(grid.cv_results_["params"]) * grid.n_splits_,
        "best_params": strip_prefix(grid.best_params_),
        "best_cv": float(grid.best_score_),
        "best_std": table[0]["std"],
        "worst": table[-1],
        "fold_scores": [
            float(grid.cv_results_[f"split{i}_test_score"][grid.best_index_]) for i in range(grid.n_splits_)
        ],
    }


def make_figure(table: list[dict]) -> str:
    """12 通りの成績を learning_rate（対数目盛）の折れ線で描く。誤差棒は標準偏差。"""
    import matplotlib.pyplot as plt

    groups: dict[tuple[int, int], list[dict]] = {}
    for row in table:
        groups.setdefault((row["n_estimators"], row["num_leaves"]), []).append(row)

    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    markers = ["o", "s", "^", "D"]
    for (n_estimators, num_leaves), marker in zip(sorted(groups), markers):
        rows = sorted(groups[(n_estimators, num_leaves)], key=lambda row: row["learning_rate"])
        ax.errorbar(
            [row["learning_rate"] for row in rows],
            [row["mean"] for row in rows],
            yerr=[row["std"] for row in rows],
            marker=marker,
            capsize=3,
            label=f"木 {n_estimators} 本・葉 {num_leaves} 枚",
        )
    ax.set_xscale("log")
    ax.set_xticks([0.02, 0.05, 0.1])
    ax.set_xticklabels(["0.02", "0.05", "0.1"])
    ax.minorticks_off()
    ax.set_xlabel("learning_rate（対数目盛）")
    ax.set_ylabel("交差検証の ROC AUC（5 分割の平均）")
    ax.set_title("グリッドサーチ 12 通りの成績（誤差棒は fold ごとのばらつき）")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, loc="lower left")
    path = save_figure(fig, FIGURE_NAME)
    return str(path.relative_to(OUT_DIR.parent))


def main() -> None:
    df = load_review_table()
    result = search(df)

    print("■ 探索空間")
    for key, values in PARAM_GRID.items():
        print(f"{key:<24}: {values}")
    print(f"組み合わせ数 {result['n_combinations']} 通り × 5 分割 = {result['n_fits']} 回の学習")
    print()

    print("■ 成績の良い順（上位 3 件）")
    print("順位 | 設定                                             | CV の平均 | 標準偏差")
    for row in result["table"][:3]:
        print(f"{row['rank']:>3}  | {format_params(row):<48} | {row['mean']:.4f}    | {row['std']:.4f}")
    print()

    worst = result["worst"]
    print("■ 最下位")
    print(f"{worst['rank']:>3}  | {format_params(worst):<48} | {worst['mean']:.4f}    | {worst['std']:.4f}")
    print()

    print("■ 選ばれた設定")
    print(f"best_params_ : {result['best_params']}")
    print(f"best_score_  : {result['best_cv']:.4f}")
    print(f"その設定の fold ごとの ROC AUC : {fmt_scores(result['fold_scores'])}")
    print()
    print(f"図を保存しました: {make_figure(result['table'])}")


if __name__ == "__main__":
    main()
