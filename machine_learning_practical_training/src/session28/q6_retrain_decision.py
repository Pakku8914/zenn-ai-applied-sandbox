"""問題6 の解答: 月次 AUC からトレンドの有無を判定し、再学習の判断基準を作る。

使い方:
    docker compose exec lab python src/session28/q6_retrain_decision.py
"""

from __future__ import annotations

from common import (
    BAND_SIGMA,
    MONITOR_MONTHS,
    SLOPE_LIMIT,
    cancel_time_split,
    monthly_auc,
    print_rules,
    retrain_rules,
    should_retrain,
    trend_summary,
)

# セッション24 の実測値（同じ時期のデータを無作為に分けた場合）
S24_ROC_AUC = 0.7911
S24_PR_AUC = 0.1827


def analyze() -> dict:
    """性能・トレンド・再学習の判断を 1 つの辞書にまとめる。"""
    split = cancel_time_split()
    table = monthly_auc()
    trend = trend_summary(table)
    rules = retrain_rules()
    return {
        "split": split,
        "table": table,
        "trend": trend,
        "rules": rules,
        "decision": should_retrain(rules),
        "roc_gap": split["roc_auc"] - S24_ROC_AUC,
        "pr_gap": split["pr_auc"] - S24_PR_AUC,
    }


def main() -> None:
    result = analyze()
    split, trend = result["split"], result["trend"]

    print("■ 1. 時間で分けた性能")
    print(
        f"学習 {split['n_train']:,} 件（〜{split['train_end'].date()}）"
        f" → 評価 {split['n_test']:,} 件"
    )
    print(f"ROC AUC {split['roc_auc']:.4f} / PR-AUC {split['pr_auc']:.4f}")
    print(
        f"セッション24（無作為分割）との差: ROC AUC {result['roc_gap']:+.4f}"
        f" / PR-AUC {result['pr_gap']:+.4f}"
    )
    print()

    print(f"■ 2. 直近 {MONITOR_MONTHS} か月の ROC AUC")
    print("月       | ROC AUC | 下限を下回ったか")
    for row in result["table"].itertuples():
        below = row.roc_auc < trend["lower"]
        print(f"{row.month}  | {row.roc_auc:>7.4f} | {'はい' if below else 'いいえ'}")
    print(
        f"平均 {trend['mean']:.4f} / 標準偏差 {trend['std']:.4f}"
        f" / 下限 {trend['lower']:.4f} / 上限 {trend['upper']:.4f}"
    )
    print(f"最小 {trend['min']:.4f} / 最大 {trend['max']:.4f}（幅 {trend['span']:.4f}）")
    print()

    print("■ 3. トレンドの判定")
    print(f"[1] 直近が下限を下回るか: {'はい' if trend['latest_below'] else 'いいえ'}")
    print(f"[2] 2 か月連続で下回るか: {'はい' if trend['consecutive_below'] else 'いいえ'}")
    print(
        f"[3] 傾きが {SLOPE_LIMIT} より急か: {'はい' if trend['slope_declining'] else 'いいえ'}"
        f"（傾き {trend['slope']:+.4f}）"
    )
    print(f"結論: {'下降トレンドがある' if trend['declining'] else '下降トレンドは無い（ばらつきの範囲）'}")
    print()

    print("■ 4. 再学習の判断")
    print_rules(result["rules"])
    decision = result["decision"]
    print(
        f"判定: 発火 {decision['n_fired']} / {decision['n_rules']} 件"
        f" → {'再学習する' if decision['retrain'] else '再学習しない'}"
    )
    print()

    print("■ 5. 1 か月下がっただけで再学習しない理由（3 文）")
    print(f"この 6 か月の AUC は {trend['span']:.4f} の幅で上下していて、これはばらつきです。")
    print(f"平均 ± {BAND_SIGMA:.0f}σ の範囲に収まっている低下を「劣化」と呼ぶと、毎月再学習することになります。")
    print("再学習は無料ではないので、発火の条件を決めておき、それを満たしたときだけ動かします。")


if __name__ == "__main__":
    main()
