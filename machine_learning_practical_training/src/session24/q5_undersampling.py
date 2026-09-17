"""問題5 の解答: 訓練データだけを 1:1 にそろえ、評価データでの指標を比べる。

実行:
    docker compose exec lab python src/session24/q5_undersampling.py
"""

from __future__ import annotations

from common import (
    baseline_scores,
    cancel_probabilities,
    load_cancel_table,
    score_summary,
    split_xy,
    undersample,
)


def compare() -> dict[str, object]:
    """アンダーサンプリングの前後の件数と、評価データでの指標をまとめる。"""
    X_train, X_test, y_train, _ = split_xy(load_cancel_table())
    X_res, y_res = undersample(X_train, y_train)

    y_test, plain = cancel_probabilities("plain")
    _, under = cancel_probabilities("under")
    plain_scores = score_summary(y_test, plain)
    under_scores = score_summary(y_test, under)
    rate = baseline_scores(y_test)["positive_rate"]

    return {
        "n_before": len(X_train),
        "n_before_positive": int(y_train.sum()),
        "n_before_negative": int(len(y_train) - y_train.sum()),
        "n_after": len(X_res),
        "n_after_positive": int(y_res.sum()),
        "n_after_negative": int(len(y_res) - y_res.sum()),
        "n_test": len(X_test),
        "rate_after": float(y_res.mean()),
        "plain": plain_scores,
        "under": under_scores,
        "positive_rate": rate,
        "pr_improved": under_scores["pr_auc"] > plain_scores["pr_auc"],
        "brier_worse": under_scores["brier"] > plain_scores["brier"],
        "mean_close": abs(under_scores["mean_proba"] - rate) < 0.05,
    }


def main() -> None:
    result = compare()
    plain, under = result["plain"], result["under"]

    print("■ 1. 件数")
    print(f"元の訓練データ: {result['n_before']:,} 件"
          f"（正例 {result['n_before_positive']:,} / 負例 {result['n_before_negative']:,}）")
    print(f"1:1 にした後  : {result['n_after']:,} 件"
          f"（正例 {result['n_after_positive']:,} / 負例 {result['n_after_negative']:,}）")
    print(f"捨てた負例    : {result['n_before_negative'] - result['n_after_negative']:,} 件")
    print(f"そろえた後の正例率: {result['rate_after']:.4f}")
    print(f"評価データ    : {result['n_test']:,} 件（手を加えていない）")
    print()

    print("■ 2. 指標の比較")
    print("指標           | 重みなし | 1:1 アンダー")
    print(f"ROC AUC        |  {plain['roc_auc']:.4f}  |  {under['roc_auc']:.4f}")
    print(f"PR-AUC         |  {plain['pr_auc']:.4f}  |  {under['pr_auc']:.4f}")
    print(f"予測確率の平均 |  {plain['mean_proba']:.4f}  |  {under['mean_proba']:.4f}")
    print(f"Brier スコア   | {plain['brier']:.5f}  | {under['brier']:.5f}")
    print()

    print("■ 3. 判定")
    print(f"PR-AUC は改善したか        : {result['pr_improved']}")
    print(f"Brier は悪化したか         : {result['brier_worse']}")
    print(f"確率の平均は正例率に近いか : {result['mean_close']}"
          f"（{under['mean_proba']:.4f} に対して実際は {result['positive_rate']:.4f}）")
    print()

    print("■ 4. 評価データにも同じ操作を当ててはいけない理由")
    print("評価データを 1:1 にすると正例率が 0.5 になり、PR-AUC のベースラインも 0.5 に上がります。")
    print("数字は必ず良く見えますが、それは本番の正例率 0.0360 の世界とは別の問題を測った結果です。")


if __name__ == "__main__":
    main()
