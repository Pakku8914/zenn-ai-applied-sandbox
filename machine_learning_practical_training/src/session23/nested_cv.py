"""ネストした交差検証 ― 探索とモデル評価を分ける（本文 7 節）。

全量で回すと学習回数が跳ね上がるため、ここでは
**訓練データの先頭 2,000 行・内側 3 分割・2 通り**に縮めた版を実行します。
構造（外側で評価し、内側で探索する）は全量版とまったく同じです。

実行:
    docker compose exec lab python src/session23/nested_cv.py
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
    space_size,
    split_train_test,
    stratified_cv,
    summarize,
)

# 縮小版の探索空間（2 通り）。全量版では grid_search.PARAM_GRID の 12 通りを使う
SMALL_GRID = {"model__learning_rate": [0.05, 0.1]}
SAMPLE_ROWS = 2000
INNER_SPLITS = 3


def cost_table() -> list[dict]:
    """やり方ごとに「何回 fit するか」を数える（机上の計算。学習はしない）。"""
    return [
        {"label": "探索なしの交差検証", "formula": "5", "fits": N_SPLITS},
        {"label": "グリッドサーチ（12 通り）", "formula": "12 × 5", "fits": 12 * N_SPLITS},
        {
            "label": "ネスト（外 5 × 内 5 × 12 通り）",
            "formula": "5 × 5 × 12",
            "fits": N_SPLITS * N_SPLITS * 12,
        },
        {
            "label": "ネスト（上記 ＋ 外側の学習し直し）",
            "formula": "5 × 5 × 12 + 5",
            "fits": N_SPLITS * N_SPLITS * 12 + N_SPLITS,
        },
        {
            # 本ファイルの nested_scores() が実際に回す規模（学習回数を抑えた版）
            "label": f"本問の縮小版（外 5 × 内 {INNER_SPLITS} × {space_size(SMALL_GRID)} 通り）",
            "formula": f"5 × {INNER_SPLITS} × {space_size(SMALL_GRID)} + 5",
            "fits": N_SPLITS * INNER_SPLITS * space_size(SMALL_GRID) + N_SPLITS,
        },
    ]


def nested_scores(df, sample_rows: int = SAMPLE_ROWS, param_grid: dict | None = None):
    """ネストした交差検証。外側の fold ごとに「内側で探索 → 外側で評価」を繰り返す。

    cross_val_score に **GridSearchCV そのものを渡す**のが要点です。外側の fold の
    検証データは、内側の探索からは完全に見えません。
    """
    X_train, _, y_train, _ = split_train_test(df)
    X_small = X_train.iloc[:sample_rows]
    y_small = y_train.iloc[:sample_rows]
    inner = StratifiedKFold(n_splits=INNER_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    searcher = GridSearchCV(
        build_model(),
        SMALL_GRID if param_grid is None else param_grid,
        scoring=SCORING,
        cv=inner,
        n_jobs=1,
    )
    # 外側の分割はいつもの層化 5 分割
    return cross_val_score(searcher, X_small, y_small, cv=stratified_cv(), scoring=SCORING)


def main() -> None:
    print("■ やり方ごとの学習回数（探索空間 12 通り・5 分割の場合）")
    print("やり方                                           | 計算式         | 学習回数")
    for row in cost_table():
        print(f"{row['label']:<46} | {row['formula']:<14} | {row['fits']:>4} 回")
    print()

    df = load_review_table()
    scores = nested_scores(df)
    mean, std = summarize(scores)
    print(f"■ 縮小版のネストした交差検証（先頭 {SAMPLE_ROWS} 行・内側 {INNER_SPLITS} 分割・2 通り）")
    print(f"外側 fold ごとの ROC AUC : {fmt_scores(scores)}")
    print(f"平均                     : {mean:.4f}")
    print(f"標準偏差                 : {std:.4f}")
    print()
    print("この平均は『この手順で作ったモデルの実力』の見積もりです。")
    print("『いちばん良いパラメータ』を知るための道具ではありません（fold ごとに違う設定が選ばれます）。")


if __name__ == "__main__":
    main()
