"""問題5 の解答: 時系列分割の中身（期間と件数）を表にして、スコアと一緒に確認する。

実行:
    docker compose exec lab python src/session22/q5_timeseries_cv.py
"""

from __future__ import annotations

import pandas as pd

from common import cv_auc, features_target, fmt_scores, load_review_table, series_cv, stratified_cv, summarize


def fold_table(ordered) -> list[dict[str, object]]:
    """fold ごとの訓練件数・評価件数と、期間の切れ目を集める。"""
    X, y = features_target(ordered)
    dates = ordered["reviewed_at"].to_numpy()
    rows = []
    for number, (train_index, test_index) in enumerate(series_cv().split(X, y), start=1):
        rows.append(
            {
                "fold": number,
                "n_train": len(train_index),
                "n_test": len(test_index),
                "train_end": pd.Timestamp(dates[train_index[-1]]).date(),
                "test_start": pd.Timestamp(dates[test_index[0]]).date(),
                "test_end": pd.Timestamp(dates[test_index[-1]]).date(),
                # 並べ替えてあるので、訓練の最後の日が評価の最初の日を追い越すことはない
                "in_order": bool(dates[train_index[-1]] <= dates[test_index[0]]),
            }
        )
    return rows


def analyze(df) -> dict[str, object]:
    """時系列分割と、shuffle する層化分割を並べて比べる。"""
    ordered = df.sort_values("reviewed_at")  # 並べてから分割する（並び順が分割の条件になる）
    scores = cv_auc(ordered, series_cv())
    mean, std = summarize(scores)
    strat_mean, _ = summarize(cv_auc(df, stratified_cv()))
    rows = fold_table(ordered)
    return {
        "rows": rows,
        "scores": scores,
        "mean": mean,
        "std": std,
        "strat_mean": strat_mean,
        "all_in_order": all(row["in_order"] for row in rows),
        "train_grows": all(rows[i]["n_train"] < rows[i + 1]["n_train"] for i in range(len(rows) - 1)),
        "test_sizes_equal": len({row["n_test"] for row in rows}) == 1,
        # 先頭のかたまりは、どの fold でも訓練側にしか回らない（評価に一度も使われない）
        "never_evaluated": rows[0]["n_train"],
        "covers_all": bool(rows[0]["n_train"] + sum(row["n_test"] for row in rows) == len(df)),
    }


def main() -> None:
    result = analyze(load_review_table())

    print("■ 1. fold の中身")
    print("fold | 訓練件数 | 評価件数 | 訓練の最終日 | 評価の期間")
    for row in result["rows"]:
        print(
            f"{row['fold']:>4} | {row['n_train']:>8} | {row['n_test']:>8} | "
            f"{row['train_end']} | {row['test_start']} 〜 {row['test_end']}"
        )
    print()

    print("■ 2. ROC AUC")
    print(f"fold ごと : {fmt_scores(result['scores'])}")
    print(f"平均      : {result['mean']:.4f}")
    print(f"標準偏差  : {result['std']:.4f}")
    print(f"層化 5 分割（shuffle あり）の平均: {result['strat_mean']:.4f}")
    print()

    print("■ 3. 判定")
    print(f"どの fold も訓練が評価より前の期間か: {result['all_in_order']}")
    print(f"訓練データは fold ごとに増えているか: {result['train_grows']}")
    print(f"評価データの件数はどの fold も同じか: {result['test_sizes_equal']}")
    print(f"一度も評価に使われない先頭の行数    : {result['never_evaluated']}")
    print(f"先頭の行数 ＋ 評価件数の合計が全件数と一致するか: {result['covers_all']}")
    print()

    print("■ 4. 説明例")
    print("時系列分割は、常に「過去で学習して未来で評価する」形になります。")
    print("そのかわり fold ごとに訓練データの量が違うので、fold 間のばらつきには")
    print("「時期の違い」と「データ量の違い」が混ざります。標準偏差の読み方が層化分割とは違います。")
    print("今回は平均がほとんど同じでした。時間とともに関係が変わっていない、という確認になります。")


if __name__ == "__main__":
    main()
