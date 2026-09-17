"""ランダムサーチ（くじ引き）で広い範囲を少ない回数で当たる（本文 4 節）。

グリッドサーチと同じく **テストデータには触りません。**

実行:
    docker compose exec lab python src/session23/random_search.py
"""

from __future__ import annotations

from sklearn.model_selection import RandomizedSearchCV

from common import (
    OUT_DIR,
    RANDOM_STATE,
    SCORING,
    build_model,
    fit_count,
    format_params,
    load_review_table,
    results_table,
    save_figure,
    space_size,
    split_train_test,
    stratified_cv,
    strip_prefix,
)
from grid_search import search as run_grid_search

FIGURE_NAME = "s23_search_points.png"

# グリッドサーチより広い範囲。どれも等比（対数スケール）で並べている
PARAM_DIST = {
    "model__n_estimators": [50, 100, 200, 400],
    "model__learning_rate": [0.01, 0.02, 0.05, 0.1, 0.2],
    "model__num_leaves": [7, 15, 31, 63],
}
N_ITER = 6  # 80 通りのうち 6 通りだけ引く


def search(df) -> dict[str, object]:
    """広い空間から 6 通りだけ引いて交差検証する。"""
    X_train, _, y_train, _ = split_train_test(df)
    random_search = RandomizedSearchCV(
        build_model(),
        PARAM_DIST,
        n_iter=N_ITER,
        scoring=SCORING,
        cv=stratified_cv(),
        n_jobs=1,  # 再現性のため 1 本で回す
        random_state=RANDOM_STATE,  # ここを固定しないと毎回違う 6 通りになる
        refit=True,
    )
    random_search.fit(X_train, y_train)
    table = results_table(random_search)
    return {
        "random_search": random_search,
        "table": table,
        "space": space_size(PARAM_DIST),
        "full_fits": fit_count(PARAM_DIST),  # 全部を総当たりしたら何回になるか
        "n_sampled": len(random_search.cv_results_["params"]),
        "n_fits": fit_count(PARAM_DIST, n_iter=N_ITER),
        "best_params": strip_prefix(random_search.best_params_),
        "best_cv": float(random_search.best_score_),
    }


def make_figure(grid_table: list[dict], random_table: list[dict]) -> str:
    """探索点の散らばりを 2 枚並べて描く。丸の大きさは n_estimators。"""
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.3), sharex=True, sharey=True)
    panels = [
        (f"グリッドサーチ（{len(grid_table)} 点）", grid_table, "tab:blue"),
        (f"ランダムサーチ（{len(random_table)} 点）", random_table, "tab:orange"),
    ]
    for ax, (title, rows, color) in zip(axes, panels):
        ax.scatter(
            [row["learning_rate"] for row in rows],
            [row["num_leaves"] for row in rows],
            s=[row["n_estimators"] * 0.6 for row in rows],
            alpha=0.55,
            color=color,
            edgecolor="black",
        )
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xticks([0.01, 0.02, 0.05, 0.1, 0.2])
        ax.set_xticklabels(["0.01", "0.02", "0.05", "0.1", "0.2"])
        ax.set_yticks([7, 15, 31, 63])
        ax.set_yticklabels(["7", "15", "31", "63"])
        ax.minorticks_off()
        ax.set_xlim(0.007, 0.3)
        ax.set_ylim(5, 95)
        ax.set_xlabel("learning_rate（対数目盛）")
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
    axes[0].set_ylabel("num_leaves（対数目盛）")
    fig.suptitle("探索点の散らばり（丸の大きさが n_estimators）")
    path = save_figure(fig, FIGURE_NAME)
    return str(path.relative_to(OUT_DIR.parent))


def main() -> None:
    df = load_review_table()
    result = search(df)

    print("■ 探索空間（グリッドサーチより広い）")
    for key, values in PARAM_DIST.items():
        print(f"{key:<24}: {values}")
    print(f"空間の大きさ {result['space']} 通り（総当たりなら {result['full_fits']} 回の学習）")
    print(f"実際に引いたのは {result['n_sampled']} 通り = {result['n_fits']} 回の学習")
    print()

    print("■ 引いた 6 通りの成績（良い順）")
    print("順位 | 設定                                             | CV の平均 | 標準偏差")
    for row in result["table"]:
        print(f"{row['rank']:>3}  | {format_params(row):<48} | {row['mean']:.4f}    | {row['std']:.4f}")
    print()

    print("■ 選ばれた設定")
    print(f"best_params_ : {result['best_params']}")
    print(f"best_score_  : {result['best_cv']:.4f}")
    print()

    grid_result = run_grid_search(df)
    print("■ グリッドサーチとの比較")
    print(f"グリッドサーチ  : {grid_result['n_fits']} 回の学習で CV {grid_result['best_cv']:.4f}")
    print(f"ランダムサーチ  : {result['n_fits']} 回の学習で CV {result['best_cv']:.4f}")
    print()
    print(f"図を保存しました: {make_figure(grid_result['table'], result['table'])}")


if __name__ == "__main__":
    main()
