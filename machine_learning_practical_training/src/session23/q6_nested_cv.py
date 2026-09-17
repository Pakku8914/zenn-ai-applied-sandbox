"""問題6（発展）: ネストした交差検証を書き、学習回数を数える。

実行:
    docker compose exec lab python src/session23/q6_nested_cv.py
"""

from __future__ import annotations

from sklearn.model_selection import GridSearchCV, StratifiedKFold, cross_val_score

from common import (
    N_SPLITS,
    RANDOM_STATE,
    SCORING,
    build_model,
    fmt_scores,
    load_review_table,
    split_train_test,
    stratified_cv,
    summarize,
)

# 縮小版の設定（全量・12 通りで回すと 300 回の学習になるため）
SAMPLE_ROWS = 2000
INNER_SPLITS = 3
SMALL_GRID = {"model__learning_rate": [0.05, 0.1]}


def nested_fit_count(outer: int, inner: int, size: int, refit: bool = True) -> int:
    """ネストした交差検証の学習回数。外側 fold ごとに内側の探索を丸ごと 1 回やる。"""
    return outer * inner * size + (outer if refit else 0)


def cost_rows() -> list[dict]:
    """やり方ごとの学習回数を並べる（机上の計算）。"""
    return [
        {"label": "探索なしの交差検証", "fits": N_SPLITS},
        {"label": "グリッドサーチ（12 通り）", "fits": 12 * N_SPLITS},
        {"label": "ネスト（外 5 × 内 5 × 12 通り）", "fits": nested_fit_count(5, 5, 12, refit=False)},
        {"label": "ネスト（上記 ＋ 外側の学習し直し）", "fits": nested_fit_count(5, 5, 12)},
        {"label": "本問の縮小版（外 5 × 内 3 × 2 通り）", "fits": nested_fit_count(5, INNER_SPLITS, 2)},
    ]


def analyze(df) -> dict[str, object]:
    """縮小版のネストした交差検証を実行し、外側 5 つのスコアを返す。"""
    X_train, _, y_train, _ = split_train_test(df)
    X_small = X_train.iloc[:SAMPLE_ROWS]
    y_small = y_train.iloc[:SAMPLE_ROWS]
    inner = StratifiedKFold(n_splits=INNER_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    searcher = GridSearchCV(build_model(), SMALL_GRID, scoring=SCORING, cv=inner, n_jobs=1)
    # cross_val_score に GridSearchCV そのものを渡す ― これがネストの正体
    scores = cross_val_score(searcher, X_small, y_small, cv=stratified_cv(), scoring=SCORING)
    mean, std = summarize(scores)
    return {
        "n_sample": len(X_small),
        "scores": [float(score) for score in scores],
        "mean": mean,
        "std": std,
        "n_outer": len(scores),
        "cost_rows": cost_rows(),
        "full_nested_fits": nested_fit_count(5, 5, 12, refit=False),
        "in_range": all(0.5 <= float(score) <= 1.0 for score in scores),
    }


def main() -> None:
    df = load_review_table()
    result = analyze(df)

    print("■ 1. やり方ごとの学習回数")
    print("やり方                                   | 学習回数")
    for row in result["cost_rows"]:
        print(f"{row['label']:<38} | {row['fits']:>4} 回")
    print()

    print(f"■ 2. 縮小版のネストした交差検証（先頭 {result['n_sample']} 行・内側 {INNER_SPLITS} 分割・2 通り）")
    print(f"外側 fold ごとの ROC AUC : {fmt_scores(result['scores'])}")
    print(f"平均 / 標準偏差          : {result['mean']:.4f} / {result['std']:.4f}")
    print(f"外側の fold 数           : {result['n_outer']}")
    print()

    print("■ 3. 説明")
    print("ネストした交差検証が返すのは『探索を含む手順そのものの実力』の見積もりです。外側の検証データは")
    print("内側の探索から完全に隠れているので、探索の分の甘さが入りません。代わりに学習回数が跳ね上がるため、")
    print("使うのは『この手順を報告に使ってよいか』を判断したいときだけにします。")
    print("最終的に配るモデルは、全訓練データで探索し直した 1 つを使います。")


if __name__ == "__main__":
    main()
