"""class_weight="balanced" が何を変えて、何を変えないのかを測る。

使い方:
    docker compose exec lab python src/session24/class_weight_effect.py
"""

from __future__ import annotations

from common import (
    DEFAULT_THRESHOLD,
    baseline_scores,
    cancel_probabilities,
    confusion_parts,
    predict_at,
    score_summary,
)


def compare() -> dict[str, dict[str, float]]:
    """重みなしと class_weight="balanced" の指標を両方まとめて返す。"""
    y_test, plain = cancel_probabilities("plain")
    _, weighted = cancel_probabilities("balanced")
    return {
        "plain": score_summary(y_test, plain),
        "balanced": score_summary(y_test, weighted),
        "base": baseline_scores(y_test),
        "plain_parts": confusion_parts(y_test, predict_at(plain, DEFAULT_THRESHOLD)),
        "balanced_parts": confusion_parts(y_test, predict_at(weighted, DEFAULT_THRESHOLD)),
    }


def main() -> None:
    result = compare()
    plain, balanced, base = result["plain"], result["balanced"], result["base"]

    print("■ 1. 順位を付ける力（閾値に依存しない指標）")
    print("指標    | 重みなし | balanced")
    print(f"ROC AUC |  {plain['roc_auc']:.4f}  |  {balanced['roc_auc']:.4f}")
    print(f"PR-AUC  |  {plain['pr_auc']:.4f}  |  {balanced['pr_auc']:.4f}")
    tolerance = 0.005  # 本書の許容誤差。これ未満の差は「差が出ていない」と扱う
    print(f"どちらの差も許容誤差 {tolerance} の内側か: "
          f"{abs(balanced['roc_auc'] - plain['roc_auc']) < tolerance and abs(balanced['pr_auc'] - plain['pr_auc']) < tolerance}")
    print()

    print("■ 2. 閾値 0.5 で切ったときの指標")
    print("指標   | 重みなし | balanced")
    print(f"適合率 |  {plain['precision']:.4f}  |  {balanced['precision']:.4f}")
    print(f"再現率 |  {plain['recall']:.4f}  |  {balanced['recall']:.4f}")
    print()

    print("■ 3. 確率そのもの（ここが壊れる）")
    print("指標           | 重みなし | balanced")
    print(f"予測確率の平均 |  {plain['mean_proba']:.4f}  |  {balanced['mean_proba']:.4f}")
    print(f"Brier スコア   | {plain['brier']:.5f}  | {balanced['brier']:.5f}")
    print(f"実際の正例率   |  {base['positive_rate']:.4f}  |  {base['positive_rate']:.4f}")
    print()

    print("■ 4. 閾値 0.5 で捕まえた件数（実際のキャンセル 541 件のうち）")
    print(f"重みなし : {result['plain_parts']['tp']:,} 件（見逃し {result['plain_parts']['fn']:,} 件）")
    print(f"balanced : {result['balanced_parts']['tp']:,} 件（見逃し {result['balanced_parts']['fn']:,} 件）")


if __name__ == "__main__":
    main()
