"""問題3 の解答: 閾値の表を作り、業務の制約から運用する閾値を選ぶ。

実行:
    docker compose exec lab python src/session24/q3_threshold_table.py
"""

from __future__ import annotations

from common import (
    best_f1_row,
    cancel_probabilities,
    print_threshold_table,
    threshold_table,
)

# 1 日に人手で確認できる件数（業務側から与えられる制約）
CAPACITY = 500


def choose(rows: list[dict[str, float]], capacity: int = CAPACITY) -> dict[str, object]:
    """確認できる件数に収まる閾値のうち、いちばん再現率が高いものを選ぶ。"""
    allowed = [row for row in rows if row["n_positive"] <= capacity]
    best = max(allowed, key=lambda row: row["recall"])
    return {
        "allowed_thresholds": [row["threshold"] for row in allowed],
        "chosen": best,
        "best_f1": best_f1_row(rows),
    }


def main() -> None:
    y_test, proba = cancel_probabilities("plain")
    rows = threshold_table(y_test, proba)
    result = choose(rows)
    chosen, best_f1 = result["chosen"], result["best_f1"]

    print("■ 1. 閾値ごとの指標（実際のキャンセル 541 件）")
    print_threshold_table(rows)
    print()

    print("■ 2. F1 がいちばん高い閾値")
    print(f"{best_f1['threshold']:.1f}（F1 {best_f1['f1']:.4f}）")
    print()

    print(f"■ 3. 「1 日に確認できるのは {CAPACITY} 件まで」の制約で選ぶ")
    print(f"条件を満たす閾値: {result['allowed_thresholds']}")
    print(f"選んだ閾値      : {chosen['threshold']:.1f}")
    print(f"  陽性と予測    : {chosen['n_positive']:,} 件")
    print(f"  再現率        : {chosen['recall']:.4f}")
    print(f"  適合率        : {chosen['precision']:.4f}")
    print(f"  捕まえた / 空振り: {chosen['tp']:,} / {chosen['fp']:,} 件")
    print()

    print("■ 4. 説明")
    print("F1 がいちばん高いのは 0.1 ですが、その閾値では 1,340 件の確認が必要になります。")
    print("確認できる件数が決まっているなら、その中でいちばん多く捕まえられる閾値を選びます。")
    print("閾値は指標が決めるものではなく、業務の制約が決めるものです。")


if __name__ == "__main__":
    main()
