"""性能の劣化を監視する（本文 7 節）。

時間で分けて学習・評価し、月ごとの ROC AUC を並べます。
月次の値は必ずばらつきます。**1 か月下がっただけで「劣化した」と言わない**ための
判定手続きを、ここで決めておきます。

使い方:
    docker compose exec lab python src/session28/performance_decay.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    BAND_SIGMA,
    MONITOR_MONTHS,
    SLOPE_LIMIT,
    SPLIT_DATE,
    cancel_time_split,
    monthly_auc,
    save_figure,
    trend_summary,
)

FIGURE_NAME = "s28_monthly_auc.png"

# セッション24 の実測値（同じ時期のデータを無作為に分けた場合）。比較の相手として使う
S24_ROC_AUC = 0.7911
S24_PR_AUC = 0.1827


def draw(table, trend: dict, name: str = FIGURE_NAME) -> str:
    """月次の AUC を折れ線にし、平均と「ばらつきの範囲」を重ねる。"""
    fig, ax = plt.subplots(figsize=(9.0, 4.6))
    ax.fill_between(
        table["month"], trend["lower"], trend["upper"], color="#4c78a8", alpha=0.12,
        label=f"ばらつきの範囲（平均 ± {BAND_SIGMA:.0f}σ）",
    )
    ax.axhline(trend["mean"], color="#4c78a8", linestyle="--", linewidth=1.2, label=f"平均 {trend['mean']:.4f}")
    ax.plot(table["month"], table["roc_auc"], marker="o", color="#e45756", label="月次 ROC AUC")
    for month, value in zip(table["month"], table["roc_auc"]):
        ax.annotate(f"{value:.4f}", (month, value), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9)
    ax.set_ylim(0.68, 0.82)
    ax.set_ylabel("ROC AUC")
    ax.set_xlabel("注文の月")
    ax.set_title("月次の性能は上下する ― この幅を知らないと「劣化」を見誤る")
    ax.legend(loc="lower left", fontsize=9)
    return save_figure(fig, name)


def main() -> None:
    split = cancel_time_split()
    print("■ 1. 時間で分けて学習する")
    print(f"境目: {SPLIT_DATE.date()}")
    print(f"学習: {split['n_train']:,} 件（最終日 {split['train_end'].date()}）")
    print(f"評価: {split['n_test']:,} 件（学習より後の注文だけ）")
    print(f"ROC AUC: {split['roc_auc']:.4f}")
    print(f"PR-AUC : {split['pr_auc']:.4f}")
    print()

    print("■ 2. 同じ時期のデータを無作為に分けた場合（セッション24）と比べる")
    print(f"無作為に分割（セッション24）: ROC AUC {S24_ROC_AUC:.4f} / PR-AUC {S24_PR_AUC:.4f}")
    print(f"時間で分割（この章）        : ROC AUC {split['roc_auc']:.4f} / PR-AUC {split['pr_auc']:.4f}")
    print(
        f"差                          : ROC AUC {split['roc_auc'] - S24_ROC_AUC:+.4f}"
        f" / PR-AUC {split['pr_auc'] - S24_PR_AUC:+.4f}"
    )
    print("→ 無作為に分けた評価は、運用の見積もりとしては甘く出ます。")
    print()

    table = monthly_auc()
    trend = trend_summary(table)
    print(f"■ 3. 直近 {MONITOR_MONTHS} か月の ROC AUC")
    print("月       | ROC AUC")
    for row in table.itertuples():
        print(f"{row.month}  | {row.roc_auc:>7.4f}")
    print(
        f"平均 {trend['mean']:.4f} / 標準偏差 {trend['std']:.4f}"
        f" / 最小 {trend['min']:.4f} / 最大 {trend['max']:.4f}（幅 {trend['span']:.4f}）"
    )
    print(f"ばらつきの範囲（平均 ± {BAND_SIGMA:.0f}σ）: {trend['lower']:.4f} 〜 {trend['upper']:.4f}")
    print()

    print("■ 4. 「下降トレンドがあるか」を決まった手続きで判定する")
    print(
        f"[1] 直近の月（{trend['months'][-1]} の {trend['latest']:.4f}）が"
        f"下限 {trend['lower']:.4f} を下回るか: {'はい' if trend['latest_below'] else 'いいえ'}"
    )
    print(
        f"[2] 下限を 2 か月連続で下回るか: {'はい' if trend['consecutive_below'] else 'いいえ'}"
        f"（下回った月は {trend['n_below']} か月）"
    )
    print(
        f"[3] 1 か月あたりの傾きが {SLOPE_LIMIT} より急に下がっているか:"
        f" {'はい' if trend['slope_declining'] else 'いいえ'}（傾き {trend['slope']:+.4f}）"
    )
    print(f"→ {'下降トレンドがある' if trend['declining'] else '下降トレンドは無い（ばらつきの範囲）'}")
    print()
    print("注意: いちばん最後の月は基準日の 1 日分しかありません。件数が少ない月の")
    print("      AUC は大きく揺れるので、月次の値は必ず件数といっしょに見ます。")

    print(f"図を保存しました: outputs/{draw(table, trend)}")


if __name__ == "__main__":
    main()
