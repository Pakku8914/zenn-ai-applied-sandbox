"""課題3・課題7 の解答: 閾値の表を作り、対応できる件数から運用する閾値を決める。

実行:
    docker compose exec lab python src/mid02/thresholds.py
"""

from __future__ import annotations

from common import (
    BUSINESS_DAYS,
    CALLS_PER_DAY,
    MONTHLY_CAPACITY,
    OPERATORS,
    baseline_scores,
    cancel_probabilities,
    choose_threshold,
    format_calls,
    print_threshold_table,
    threshold_table,
)


def capacity_plan(capacity: int = MONTHLY_CAPACITY) -> dict[str, object]:
    """閾値ごとに「その連絡枠で回るか」を判定し、選んだ閾値を返す。"""
    y_test, proba = cancel_probabilities("plain")
    rows = threshold_table(y_test, proba)
    for row in rows:
        row["fits"] = row["n_positive"] <= capacity
        row["gap"] = abs(row["n_positive"] - capacity)
        row["load_ratio"] = row["n_positive"] / capacity
    return {
        "capacity": capacity,
        "rows": rows,
        "chosen": choose_threshold(y_test, proba, capacity),
        "best_f1": max(rows, key=lambda row: (row["f1"], -row["threshold"])),
        "n_actual_positive": baseline_scores(y_test)["n_positive"],
        "n_rows": baseline_scores(y_test)["n_rows"],
    }


def main() -> None:
    plan = capacity_plan()
    rows, chosen, best_f1 = plan["rows"], plan["chosen"], plan["best_f1"]
    capacity = plan["capacity"]

    print(f"■ 1. 閾値ごとの指標（評価データ {plan['n_rows']:,} 件・"
          f"実際のキャンセル {plan['n_actual_positive']:,} 件）")
    print_threshold_table(rows)
    print()

    print("■ 2. 対応できる件数（前提）")
    print(f"オペレーター {OPERATORS} 名 × 1 日 {CALLS_PER_DAY} 件 × {BUSINESS_DAYS} 営業日"
          f" = 月 {capacity:,} 件まで")
    print(f"評価データ {plan['n_rows']:,} 件を「これから 1 か月に入る注文」と見なす")
    print()

    print("■ 3. その枠で回るか")
    for row in rows:
        if row["fits"]:
            tail = f"余り     {row['gap']:>3,} 件・回る（捕まえる {row['tp']:,} 件）"
        else:
            tail = f"あふれる {row['gap']:>3,} 件・回らない"
        print(f"閾値 {row['threshold']:.1f} : 陽性 {row['n_positive']:>5,} 件"
              f" / 枠 {capacity:,} 件 → {tail}")
    print(f"いちばん下げた閾値 0.1 は、枠の {rows[0]['load_ratio']:.2f} 倍の件数になります")
    print()

    print("■ 4. 選んだ閾値")
    print(f"閾値 {chosen['threshold']:.1f}（枠で回る範囲で再現率が最大）")
    print(f"再現率 {chosen['recall']:.4f} / 適合率 {chosen['precision']:.4f}"
          f" / 陽性 {chosen['n_positive']:,} 件 / 捕まえる {chosen['tp']:,} 件"
          f" / 見逃す {chosen['fn']:,} 件")
    print(f"連絡 {format_calls(chosen['calls_per_catch'])}で 1 件が当たりです")
    print(f"F1 がいちばん高いのは閾値 {best_f1['threshold']:.1f}（F1 {best_f1['f1']:.4f}）ですが、"
          f"{best_f1['n_positive']:,} 件は対応できません")
    print()

    doubled = capacity_plan(MONTHLY_CAPACITY * 2)
    grown = doubled["chosen"]
    print(f"■ 5. 1 名増やすと何が変わるか（月 {doubled['capacity']:,} 件）")
    print(f"閾値 {grown['threshold']:.1f} が選べる: 陽性 {grown['n_positive']:,} 件"
          f" / 捕まえる {grown['tp']:,} 件（+{grown['tp'] - chosen['tp']:,} 件）"
          f" / 適合率 {grown['precision']:.4f}")
    print(f"連絡の件数は {grown['n_positive'] - chosen['n_positive']:,} 件増えて、"
          f"捕まえる件数は {grown['tp'] - chosen['tp']:,} 件増えます")


if __name__ == "__main__":
    main()
