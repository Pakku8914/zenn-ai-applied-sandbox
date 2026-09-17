"""問題4: RandomizedSearchCV で広い空間を 6 通りだけ引き、グリッドサーチと比べる。

実行:
    docker compose exec lab python src/session23/q4_random_search.py
"""

from __future__ import annotations

from sklearn.model_selection import ParameterSampler, RandomizedSearchCV

from common import (
    RANDOM_STATE,
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

PARAM_DIST = {
    "model__n_estimators": [50, 100, 200, 400],
    "model__learning_rate": [0.01, 0.02, 0.05, 0.1, 0.2],
    "model__num_leaves": [7, 15, 31, 63],
}
N_ITER = 6

# 問題2（グリッドサーチ）の結果。比較のための定数として置いておく
GRID_BEST_CV = 0.8143
GRID_FITS = 60


def sampled_params(random_state: int = RANDOM_STATE) -> list[dict]:
    """RandomizedSearchCV が実際に引く 6 通りを、学習せずに先に覗く。"""
    return list(ParameterSampler(PARAM_DIST, n_iter=N_ITER, random_state=random_state))


def analyze(df) -> dict[str, object]:
    """ランダムサーチを回し、学習回数と成績をグリッドサーチと比べる。"""
    X_train, _, y_train, _ = split_train_test(df)
    random_search = RandomizedSearchCV(
        build_model(),
        PARAM_DIST,
        n_iter=N_ITER,
        scoring=SCORING,
        cv=stratified_cv(),
        n_jobs=1,
        random_state=RANDOM_STATE,
    )
    random_search.fit(X_train, y_train)
    table = results_table(random_search)
    best_cv = float(random_search.best_score_)
    first = sampled_params()
    return {
        "space": space_size(PARAM_DIST),
        "full_fits": fit_count(PARAM_DIST),
        "n_fits": fit_count(PARAM_DIST, n_iter=N_ITER),
        "best_params": strip_prefix(random_search.best_params_),
        "best_cv": best_cv,
        "table": table,
        "gap_to_grid": best_cv - GRID_BEST_CV,
        "as_good_as_grid": abs(best_cv - GRID_BEST_CV) < 0.005,
        "fits_saved": GRID_FITS - fit_count(PARAM_DIST, n_iter=N_ITER),
        "same_seed_same_draw": first == sampled_params(),
        "other_seed_differs": first != sampled_params(random_state=0),
        "drew_the_winner": any(
            strip_prefix(params) == {"num_leaves": 7, "n_estimators": 400, "learning_rate": 0.02}
            for params in first
        ),
    }


def main() -> None:
    df = load_review_table()
    result = analyze(df)

    print("■ 1. 空間の大きさと実際の学習回数")
    print(f"空間 {result['space']} 通り（総当たりなら {result['full_fits']} 回）")
    print(f"引いたのは {N_ITER} 通り = {result['n_fits']} 回の学習")
    print()

    print("■ 2. 引いた 6 通り（学習する前に覗いた設定）")
    for params in sampled_params():
        print(f"  {format_params(params)}")
    print(f"同じ random_state なら同じ 6 通り : {result['same_seed_same_draw']}")
    print(f"別の random_state だと違う 6 通り : {result['other_seed_differs']}")
    print()

    print("■ 3. 成績（良い順）")
    print("順位 | 設定                                             | CV の平均 | 標準偏差")
    for row in result["table"]:
        print(f"{row['rank']:>3}  | {format_params(row):<48} | {row['mean']:.4f}    | {row['std']:.4f}")
    print()

    print("■ 4. グリッドサーチとの比較")
    print(f"グリッドサーチ : {GRID_FITS} 回の学習で CV {GRID_BEST_CV:.4f}")
    print(f"ランダムサーチ : {result['n_fits']} 回の学習で CV {result['best_cv']:.4f}")
    print(f"差             : {result['gap_to_grid']:+.4f}（同等と言えるか: {result['as_good_as_grid']}）")
    print(f"節約できた学習 : {result['fits_saved']} 回")
    print()

    print("■ 5. 説明")
    print("ランダムサーチは半分の学習回数で同じところに着きました。効くパラメータが少数（ここでは")
    print("num_leaves）のとき、くじ引きでもその軸を広く当たれるからです。総当たりでは、効かない軸の")
    print("刻みを増やすたびに学習回数が掛け算で増えてしまいます。")


if __name__ == "__main__":
    main()
