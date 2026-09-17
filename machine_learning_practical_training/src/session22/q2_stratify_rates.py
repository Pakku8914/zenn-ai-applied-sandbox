"""問題2 の解答: 層化する / しないで、fold ごとの正例率とスコアのばらつきを比べる。

実行:
    docker compose exec lab python src/session22/q2_stratify_rates.py
"""

from __future__ import annotations

from common import (
    cv_auc,
    fmt_scores,
    fold_positive_rates,
    load_review_table,
    plain_cv,
    stratified_cv,
    summarize,
)


def analyze(df) -> dict[str, object]:
    """層化あり・なしの 2 通りについて、正例率とスコアを集める。"""
    overall = float(df["is_high"].mean())

    strat_rates = fold_positive_rates(df, stratified_cv())
    plain_rates = fold_positive_rates(df, plain_cv())
    strat_mean, strat_std = summarize(cv_auc(df, stratified_cv()))
    plain_mean, plain_std = summarize(cv_auc(df, plain_cv()))

    return {
        "overall": overall,
        "strat_rates": strat_rates,
        "plain_rates": plain_rates,
        # 層化ありは「全体の正例率からどれだけ離れたか」で見る（そろっているはず）
        "strat_worst_diff": max(abs(rate - overall) for rate in strat_rates),
        "plain_worst_diff": max(abs(rate - overall) for rate in plain_rates),
        "plain_spread": max(plain_rates) - min(plain_rates),
        "strat_mean": strat_mean,
        "strat_std": strat_std,
        "plain_mean": plain_mean,
        "plain_std": plain_std,
        "plain_std_is_larger": bool(plain_std > strat_std),
        "mean_gap": abs(plain_mean - strat_mean),
    }


def main() -> None:
    result = analyze(load_review_table())

    print(f"全体の正例率: {result['overall']:.4f}")
    print()

    print("■ fold ごとの検証データの正例率")
    print(f"層化あり : {fmt_scores(result['strat_rates'])}")
    print(f"層化なし : {fmt_scores(result['plain_rates'])}")
    print(f"全体からの差（最大）: 層化あり {result['strat_worst_diff']:.4f} / 層化なし {result['plain_worst_diff']:.4f}")
    print(f"層化なしの正例率の幅（最大 − 最小）: {result['plain_spread']:.4f}")
    print()

    print("■ ROC AUC")
    print(f"層化あり : 平均 {result['strat_mean']:.4f} / 標準偏差 {result['strat_std']:.4f}")
    print(f"層化なし : 平均 {result['plain_mean']:.4f} / 標準偏差 {result['plain_std']:.4f}")
    print(f"層化なしのほうが標準偏差が大きいか: {result['plain_std_is_larger']}")
    print(f"平均どうしの差: {result['mean_gap']:.4f}")
    print()

    print("■ 説明例")
    print("層化は「fold ごとの正例率を全体にそろえる」だけの仕組みです。")
    print("平均はほとんど変わりませんが、fold ごとの条件がそろうので標準偏差が小さくなります。")
    print("つまり層化は、平均を良くする道具ではなく、平均を信じやすくする道具です。")


if __name__ == "__main__":
    main()
