"""不均衡データで報告すべき指標のセットを、決まった順で出力する。

使い方:
    docker compose exec lab python src/session24/report_set.py
"""

from __future__ import annotations

from common import (
    MODEL_KINDS,
    best_f1_row,
    cancel_probabilities,
    print_report_card,
    report_card,
    score_summary,
    threshold_table,
)

# 表の見た目をそろえるため、ラベルは埋め込みではなく文字列で持つ
LABELS = {
    "plain": "重みなし                ",
    "balanced": "class_weight=balanced   ",
    "under": "1:1 アンダーサンプリング",
}


def main() -> None:
    y_test, plain = cancel_probabilities("plain")
    threshold = best_f1_row(threshold_table(y_test, plain))["threshold"]

    print_report_card(report_card(y_test, plain, threshold), "LightGBM・重みなし")
    print()

    print("■ 学習のしかたを「確率の質」で比べる")
    print("学習のしかた             | PR-AUC | 確率の平均 | Brier")
    for kind in MODEL_KINDS:
        y_true, proba = cancel_probabilities(kind)
        scores = score_summary(y_true, proba)
        print(f"{LABELS[kind]} | {scores['pr_auc']:.4f} |   {scores['mean_proba']:.4f}   | {scores['brier']:.5f}")
    print()

    print("■ 載せない指標とその理由")
    print("accuracy : 0.9640 は「全部キャンセルされない」と答えても同じ値になるため")
    print("F1 だけ  : 適合率と再現率を同じ重さで潰してしまい、業務の重みを表せないため")


if __name__ == "__main__":
    main()
