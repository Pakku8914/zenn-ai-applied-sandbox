"""問題2: GridSearchCV を層化 5 分割と組み合わせ、cv_results_ を読む。

実行:
    docker compose exec lab python src/session23/q2_grid_search.py
"""

from __future__ import annotations

from sklearn.model_selection import GridSearchCV

from common import (
    SCORING,
    build_model,
    fit_count,
    format_params,
    load_review_table,
    results_table,
    space_size,
    split_train_test,
    stratified_cv,
    strip_prefix,
)

PARAM_GRID = {
    "model__n_estimators": [50, 200],
    "model__learning_rate": [0.02, 0.05, 0.1],
    "model__num_leaves": [7, 31],
}


def analyze(df) -> dict[str, object]:
    """12 通りを総当たりし、上位 3 件・最下位・最良の設定を取り出す。"""
    X_train, _, y_train, _ = split_train_test(df)  # テストデータは受け取っても使わない
    grid = GridSearchCV(
        build_model(),
        PARAM_GRID,
        scoring=SCORING,
        cv=stratified_cv(),
        n_jobs=1,
    )
    grid.fit(X_train, y_train)
    table = results_table(grid)
    return {
        "size": space_size(PARAM_GRID),
        "planned_fits": fit_count(PARAM_GRID),
        "actual_fits": len(grid.cv_results_["params"]) * grid.n_splits_,
        "best_params": strip_prefix(grid.best_params_),
        "best_cv": float(grid.best_score_),
        "top3": table[:3],
        "worst": table[-1],
        "leaves7_is_best": all(row["num_leaves"] == 7 for row in table[:3]),
        "n_results": len(table),
    }


def main() -> None:
    df = load_review_table()
    result = analyze(df)

    print("■ 1. 探索の規模")
    print(f"組み合わせ {result['size']} 通り × 5 分割 = {result['planned_fits']} 回（実際の学習回数 {result['actual_fits']} 回）")
    print()

    print("■ 2. 成績の良い順（上位 3 件）")
    print("順位 | 設定                                             | CV の平均 | 標準偏差")
    for row in result["top3"]:
        print(f"{row['rank']:>3}  | {format_params(row):<48} | {row['mean']:.4f}    | {row['std']:.4f}")
    print()

    print("■ 3. 最下位（既定値に近い設定）")
    worst = result["worst"]
    print(f"{worst['rank']:>3}  | {format_params(worst):<48} | {worst['mean']:.4f}    | {worst['std']:.4f}")
    print()

    print("■ 4. 選ばれた設定")
    print(f"best_params_ : {result['best_params']}")
    print(f"best_score_  : {result['best_cv']:.4f}")
    print(f"上位 3 件がすべて num_leaves=7 : {result['leaves7_is_best']}")
    print()

    print("■ 5. 読み取れること（説明）")
    print("num_leaves を 31 から 7 に下げると成績が上がりました。1 万件・特徴量 5 つのデータに対して、")
    print("葉 31 枚の木は複雑すぎたということです。最下位が既定値に近い設定だという点も見逃せません。")


if __name__ == "__main__":
    main()
