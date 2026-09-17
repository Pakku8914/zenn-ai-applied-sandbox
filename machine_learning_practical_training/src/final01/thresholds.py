"""課題6: 閾値を予算から逆算する。

確率をそのまま渡しても、誰もクーポンを送れません。
「何人に送るか」に変えるには閾値が必要で、その閾値はデータではなく予算が決めます。

使い方:
    docker compose exec lab python src/final01/thresholds.py
"""

from __future__ import annotations

from common import (
    CAPACITY,
    COUPON_COST_YEN,
    MONTHLY_BUDGET_YEN,
    capacity_plan,
    dataset,
    fitted,
    threshold_table,
)


def table():
    """運用に使うモデル（LightGBM）の閾値ごとの成績を DataFrame で返す。"""
    data = dataset()
    return threshold_table(fitted("lgbm")["proba"], data["y_test"])


def main() -> None:
    data = dataset()
    rows = table()
    plan = capacity_plan(rows)

    print("■ 1. 予算の前提（データからは出てこない数字）")
    print(f"クーポン 1 通の原価: {COUPON_COST_YEN:,} 円")
    print(f"今月の販促予算    : {MONTHLY_BUDGET_YEN:,} 円")
    print(f"→ 送れるのは {CAPACITY:,} 通まで")
    print(f"（評価データ {data['n_test']:,} 人を 1 か月ぶんの配信対象と見なす）")
    print()

    print("■ 2. 閾値ごとの成績")
    for row in rows.itertuples():
        print(f"閾値 {row.threshold:.1f}")
        print(f"    適合率 {row.precision:.4f} / 再現率 {row.recall:.4f} / F1 {row.f1:.4f}")
        print(f"    送る {row.n_sent:,} 人（当たり {row.tp:,} 人 / 空振り {row.fp:,} 人 / 見逃し {row.fn:,} 人）")
        print(f"    費用 {row.cost_yen:,} 円 / 1 人捕まえるのに {row.coupons_per_hit:.2f} 通 / 予算に収まる: {row.within_budget}")
    print()

    print("■ 3. 予算から閾値を選ぶ")
    print(f"F1 がいちばん高い閾値: {plan['best_f1_threshold']:.1f}（F1 {plan['best_f1']:.4f}）")
    print(f"→ ただし送る通数が {plan['best_f1_n_sent']:,} 人で、{plan['best_f1_over']:,} 通あふれます。選べません。")
    print(f"選ぶ閾値: {plan['threshold']:.1f}（予算に収まる中で再現率が最大）")
    print(f"    送る {plan['n_sent']:,} 人 / 当たり {plan['tp']:,} 人 / 見逃し {plan['fn']:,} 人")
    print(f"    適合率 {plan['precision']:.4f} / 再現率 {plan['recall']:.4f}")
    print(f"    費用 {plan['cost_yen']:,} 円（予算の残り {plan['left_yen']:,} 円・枠の余り {plan['spare']:,} 通）")
    print()

    print("■ 4. 選ばなかった場合と比べる")
    print(f"同じ枠 {CAPACITY:,} 通を無作為に配ったときの当たり: 約 {plan['random_hits']:,} 人")
    print(f"モデルで上から {plan['n_sent']:,} 人に配ったときの当たり: {plan['tp']:,} 人")
    print(f"通数が少ないのに当たりが多いか: {plan['beats_random']}")
    print()
    print("判断: 閾値はデータからは決まりません。**送れる通数**から逆算します。")
    print("      予算が倍になれば、同じモデルでも選ぶ閾値は変わります。")


if __name__ == "__main__":
    main()
