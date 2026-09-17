"""問題10 の解答: 運用の監視を設計する（何を・どこで線を引き・何をするか）。

実行:
    docker compose exec lab python src/review03/q10_monitoring_plan.py
"""

from __future__ import annotations

from common import (
    AS_OF,
    BAND_SIGMA,
    LABEL_JA,
    MONITOR_MONTHS,
    PSI_ACT,
    PSI_WATCH,
    QUANTITY_FRACTION,
    QUANTITY_VALUE,
    RETRAIN_GROWTH,
    RETRAIN_MAX_DAYS,
    SLOPE_LIMIT,
    SPLIT_DATE,
    cancel_time_split,
    halves,
    monthly_auc,
    psi_table,
    quantity_drift,
    retrain_rules,
    save_fig,
    should_retrain,
    trend_summary,
    unit_price_drift,
)

FIGURE_NAME = "review03_monitoring.png"

# 監視の設計。**先に表を書いてから**測りに行くのが、この問題のいちばんの要点
MONITORING_PLAN = [
    {
        "what": "入力の分布（単価・数量・値引き率・売上額）",
        "how": "学習したころのデータを基準にした PSI",
        "when": "毎週",
        "watch": f"PSI {PSI_WATCH:.2f} 以上",
        "act": f"PSI {PSI_ACT:.2f} 以上",
        "then": "どの列が動いたかを特定し、原因（仕様変更・キャンペーン）を確認してから再学習",
    },
    {
        "what": "カテゴリ列の水準",
        "how": "学習時になかった値が来た件数",
        "when": "毎日",
        "watch": "1 件でも発生",
        "act": "全体の 1% 以上",
        "then": "入力検証で弾いた件数をログで確認し、水準を増やして再学習",
    },
    {
        "what": "予測の分布",
        "how": "予測確率の平均と、実際の正例率の差",
        "when": "毎週",
        "watch": "差が 0.05 以上",
        "act": "差が 0.10 以上",
        "then": "確率の校正（キャリブレーション）を見直す。閾値を決め直す",
    },
    {
        "what": "性能（正解が遅れて分かるもの）",
        "how": f"月次の ROC AUC と、平均 ± {BAND_SIGMA:.0f}σ の帯",
        "when": "毎月",
        "watch": f"平均 − {BAND_SIGMA:.0f}σ を 1 か月下回る",
        "act": f"2 か月連続で下回る、または傾きが {SLOPE_LIMIT:+.3f}/月 より急",
        "then": "同じ期間の入力の PSI と突き合わせ、原因を切り分けてから再学習",
    },
    {
        "what": "モデルの鮮度",
        "how": "学習データの最終日からの経過日数と、データ量の増え方",
        "when": "毎月",
        "watch": f"{RETRAIN_MAX_DAYS // 2} 日経過",
        "act": f"{RETRAIN_MAX_DAYS} 日経過、または学習時の {RETRAIN_GROWTH:.1f} 倍",
        "then": "定期再学習を実行し、保存したメタデータの性能と比べてから入れ替える",
    },
]


def print_plan() -> None:
    """監視設計を 1 項目 6 行で表示する（列をそろえた表にすると日本語の幅で崩れる）。"""
    for index, row in enumerate(MONITORING_PLAN, start=1):
        print(f"[{index}] {row['what']}")
        print(f"    測り方  : {row['how']}")
        print(f"    頻度    : {row['when']}")
        print(f"    注意の線: {row['watch']}")
        print(f"    発火の線: {row['act']}")
        print(f"    発火したら: {row['then']}")


def main() -> None:
    parts = halves()
    print("■ 1. いまの入力はどれだけ動いているか（PSI）")
    print(
        f"前半（{SPLIT_DATE.date()} より前）: {len(parts['before']):,} 件 /"
        f" 後半（{SPLIT_DATE.date()} 以降）: {len(parts['after']):,} 件"
    )
    print("列             |  PSI   | 判定")
    table = psi_table()
    for column, value, judgement in zip(table["column"], table["psi"], table["judgement"]):
        print(f"{LABEL_JA[str(column)]:<14} | {float(value):.4f} | {str(judgement)}")
    print("→ 4 列すべて 0.1 未満。いまのデータでは入力の分布は動いていません")
    print("（前半・後半の平均も psi_table() が返しています。動いた列を特定するときに並べてください）")
    print()

    print("■ 2. 監視が本当に反応するかを、人工のドリフトで確かめる")
    print("後半の単価を一律で何倍にしたか |  PSI   | 判定")
    drift = unit_price_drift()
    for ratio, value, judgement in zip(drift["ratio"], drift["psi"], drift["judgement"]):
        print(f"{float(ratio):>28.2f} 倍 | {float(value):.4f} | {str(judgement)}")
    quantity = quantity_drift()
    print(
        f"後半の {QUANTITY_FRACTION:.0%}（{quantity['n_changed']:,} 件）の数量を {QUANTITY_VALUE} に差し替え: "
        f"PSI {quantity['psi_plain']:.4f} → {quantity['psi_injected']:.4f}（{quantity['judgement_injected']}）"
    )
    print("→ 5% の値上げでは鳴らず、20% で発火します。線引きが妥当かは、こうして自分で確かめます")
    print()

    print("■ 3. 性能は下がっているか（時間で分けて測る）")
    split = cancel_time_split()
    print(f"学習: {split['n_train']:,} 件（最終日 {split['train_end'].date()}） → 評価: {split['n_test']:,} 件")
    print(f"ROC AUC {split['roc_auc']:.4f} / PR-AUC {split['pr_auc']:.4f}（無作為分割の 0.7911 より低い）")
    trend = trend_summary(monthly_auc())
    print(f"直近 {MONITOR_MONTHS} か月の月次 ROC AUC")
    for month, value in zip(trend["months"], trend["values"]):
        print(f"  {month}: {value:.4f}")
    print(f"平均 {trend['mean']:.4f} / 標準偏差 {trend['std']:.4f} / 平均 − {BAND_SIGMA:.0f}σ = {trend['lower']:.4f}")
    print(f"最大 − 最小 {trend['span']:.4f} / 1 か月あたりの傾き {trend['slope']:+.4f}")
    print(f"平均 − {BAND_SIGMA:.0f}σ を下回った月: {trend['n_below']} か月（連続: {trend['consecutive_below']}）")
    print(f"下降トレンドと判定するか: {trend['declining']}")
    print("→ 月ごとに 0.05 ほど上下します。1 か月下がっただけで騒がないための帯がこれです")
    print()

    print("■ 4. 監視の設計（先に表を書いてから測る）")
    print_plan()
    print()

    print("■ 5. 再学習の判断（1 つでも発火したら再学習する）")
    rules = retrain_rules()
    for index, rule in enumerate(rules, start=1):
        print(f"[{index}] {rule['name']}")
        print(f"    閾値: {rule['rule']}")
        print(f"    実測: {rule['actual']}")
        print(f"    発火: {'する' if rule['fire'] else 'しない'}")
    decision = should_retrain(rules)
    print(f"基準日 {AS_OF.date()} の判断: 再学習 {'する' if decision['retrain'] else 'しない'}")
    print(f"発火した条件 {decision['n_fired']} / {decision['n_rules']} 件: {decision['fired']}")
    print("→ 性能もデータの分布も動いていませんが、時間とデータ量の条件で再学習します")
    print()

    print(f"図を保存しました: outputs/{make_figure(trend, drift)}")


def make_figure(trend: dict, drift) -> str:
    """左: 月次 AUC と平均 ± 2σ の帯 / 右: 単価の倍率ごとの PSI と 2 本の線。"""
    import matplotlib.pyplot as plt
    import numpy as np

    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.2))

    positions = np.arange(len(trend["values"]), dtype="float64")
    axes[0].plot(positions, trend["values"], marker="o", color="#2980b9", label="月次 ROC AUC")
    axes[0].axhline(trend["mean"], color="#7f8c8d", linestyle="-", linewidth=1, label="平均")
    axes[0].axhline(trend["lower"], color="#c0392b", linestyle="--", linewidth=1, label=f"平均 ± {BAND_SIGMA:.0f}σ")
    axes[0].axhline(trend["upper"], color="#c0392b", linestyle="--", linewidth=1)
    axes[0].set_xticks(positions)
    axes[0].set_xticklabels(trend["months"], rotation=45, ha="right", fontsize=8)
    axes[0].set_ylabel("ROC AUC")
    axes[0].set_title("月次の性能は上下する（帯の中なら騒がない）")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(fontsize=8, loc="lower right")

    labels = [f"{float(ratio):.2f} 倍" for ratio in drift["ratio"]]
    values = [float(value) for value in drift["psi"]]
    bars = axes[1].bar(labels, values, color=["#2980b9", "#2980b9", "#c0392b", "#c0392b"])
    for bar, value in zip(bars, values):
        axes[1].text(bar.get_x() + bar.get_width() / 2, value + 0.02, f"{value:.4f}", ha="center", fontsize=9)
    axes[1].axhline(PSI_WATCH, color="#f39c12", linestyle="--", linewidth=1, label=f"注意 {PSI_WATCH:.2f}")
    axes[1].axhline(PSI_ACT, color="#c0392b", linestyle="--", linewidth=1, label=f"要再学習 {PSI_ACT:.2f}")
    axes[1].set_xlabel("後半の単価を何倍にしたか")
    axes[1].set_ylabel("PSI")
    axes[1].set_ylim(0.0, 1.05)
    axes[1].set_title("単価が 20% 動くと監視が発火する")
    axes[1].legend(fontsize=8)

    return save_fig(fig, FIGURE_NAME)


if __name__ == "__main__":
    main()
