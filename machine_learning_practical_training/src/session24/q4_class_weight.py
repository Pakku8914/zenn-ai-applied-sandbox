"""問題4 の解答: class_weight="balanced" が変えるものと変えないものを切り分ける。

実行:
    docker compose exec lab python src/session24/q4_class_weight.py
"""

from __future__ import annotations

from common import baseline_scores, cancel_probabilities, score_summary

TOLERANCE = 0.005  # 本書の許容誤差。これ未満の差は「差が出ていない」と扱う


def compare() -> dict[str, object]:
    """重みなしと balanced の指標を並べ、改善したかどうかを判定する。"""
    y_test, plain = cancel_probabilities("plain")
    _, weighted = cancel_probabilities("balanced")
    plain_scores = score_summary(y_test, plain)
    weighted_scores = score_summary(y_test, weighted)
    return {
        "plain": plain_scores,
        "balanced": weighted_scores,
        "positive_rate": baseline_scores(y_test)["positive_rate"],
        "roc_improved": (weighted_scores["roc_auc"] - plain_scores["roc_auc"]) > TOLERANCE,
        "pr_improved": (weighted_scores["pr_auc"] - plain_scores["pr_auc"]) > TOLERANCE,
        "recall_improved": weighted_scores["recall"] > plain_scores["recall"],
        "brier_worse": weighted_scores["brier"] > plain_scores["brier"],
        "mean_ratio": weighted_scores["mean_proba"] / plain_scores["mean_proba"],
    }


def main() -> None:
    result = compare()
    plain, weighted = result["plain"], result["balanced"]

    print("■ 1. 指標の比較")
    print("指標           | 重みなし | balanced")
    print(f"ROC AUC        |  {plain['roc_auc']:.4f}  |  {weighted['roc_auc']:.4f}")
    print(f"PR-AUC         |  {plain['pr_auc']:.4f}  |  {weighted['pr_auc']:.4f}")
    print(f"適合率（0.5）  |  {plain['precision']:.4f}  |  {weighted['precision']:.4f}")
    print(f"再現率（0.5）  |  {plain['recall']:.4f}  |  {weighted['recall']:.4f}")
    print(f"予測確率の平均 |  {plain['mean_proba']:.4f}  |  {weighted['mean_proba']:.4f}")
    print(f"Brier スコア   | {plain['brier']:.5f}  | {weighted['brier']:.5f}")
    print()

    print(f"■ 2. 判定（改善は許容誤差 {TOLERANCE} を超えた場合だけ True）")
    print(f"ROC AUC が改善したか : {result['roc_improved']}")
    print(f"PR-AUC が改善したか  : {result['pr_improved']}")
    print(f"再現率が上がったか   : {result['recall_improved']}")
    print(f"Brier が悪化したか   : {result['brier_worse']}")
    print()

    print("■ 3. 何が起きたのか")
    print("class_weight は少数クラスを間違えたときの罰を重くするだけなので、")
    print("順位の付け方（ROC AUC・PR-AUC）はほとんど変わりません。")
    print(f"変わったのは確率の目盛りで、平均が {result['mean_ratio']:.1f} 倍に膨らみました。")
    print(f"実際の正例率は {result['positive_rate']:.4f} なので、balanced の確率はもう確率として読めません。")
    print("再現率が上がったのは、同じ 0.5 で切っても実質的に低い閾値で切ったことになるからです。")


if __name__ == "__main__":
    main()
