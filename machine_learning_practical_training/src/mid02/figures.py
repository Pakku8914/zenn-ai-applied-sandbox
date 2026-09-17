"""課題9 の解答: 報告に使う図 3 枚を描いて outputs/ に保存する。

実行:
    docker compose exec lab python src/mid02/figures.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 画面のないコンテナで PNG として保存するための設定
import matplotlib.pyplot as plt

from common import (
    MONTHLY_CAPACITY,
    THRESHOLD_GRID,
    baseline_scores,
    cancel_probabilities,
    choose_threshold,
    load_order_table,
    pr_points,
    save_figure,
    score_summary,
    threshold_table,
)
from features import add_all_features, run_steps

FIGURES = ("mid02_pr_curve.png", "mid02_threshold_tradeoff.png", "mid02_leak_check.png")

BLUE = "#4c78a8"
RED = "#e45756"
GREEN = "#54a24b"
GRAY = "#999999"


def draw_pr_curve() -> Path:
    """図1: PR 曲線。ベースライン（正例率）の水平線と、運用する閾値の点を重ねる。"""
    y_test, proba = cancel_probabilities("plain")
    precision, recall, _ = pr_points(y_test, proba)
    scores = score_summary(y_test, proba)
    base = baseline_scores(y_test)
    chosen = choose_threshold(y_test, proba)

    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    ax.plot(recall, precision, color=BLUE, label=f"基準モデル（PR-AUC {scores['pr_auc']:.4f}）")
    ax.axhline(
        base["positive_rate"],
        color=GRAY,
        linestyle="--",
        label=f"ベースライン（正例率 {base['positive_rate']:.4f}）",
    )
    ax.scatter(
        [chosen["recall"]],
        [chosen["precision"]],
        color=RED,
        zorder=5,
        label=f"運用する閾値 {chosen['threshold']:.1f}（陽性 {chosen['n_positive']:,} 件）",
    )
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("再現率（recall）")
    ax.set_ylabel("適合率（precision）")
    ax.set_title(
        f"キャンセル予測の PR 曲線（評価データ {base['n_rows']:,} 件・"
        f"正例 {base['n_positive']:,} 件）"
    )
    ax.legend(loc="upper right", fontsize=9)
    return save_figure(fig, FIGURES[0])


def draw_threshold_tradeoff() -> Path:
    """図2: 閾値を動かしたときの「連絡する件数」と「適合率・再現率」。"""
    y_test, proba = cancel_probabilities("plain")
    rows = threshold_table(y_test, proba, THRESHOLD_GRID)
    chosen = choose_threshold(y_test, proba)
    thresholds = [row["threshold"] for row in rows]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))

    axes[0].plot(thresholds, [row["n_positive"] for row in rows], marker="o", markersize=3, color=BLUE)
    axes[0].axhline(
        MONTHLY_CAPACITY,
        color=RED,
        linestyle="--",
        label=f"対応できる件数（月 {MONTHLY_CAPACITY:,} 件）",
    )
    axes[0].axvline(
        chosen["threshold"], color=GREEN, linestyle=":", label=f"選んだ閾値 {chosen['threshold']:.1f}"
    )
    axes[0].set_xlabel("閾値")
    axes[0].set_ylabel("陽性と予測した件数（件）")
    axes[0].set_title("閾値を下げると連絡する件数が増える")
    axes[0].legend(fontsize=9)

    axes[1].plot(thresholds, [row["precision"] for row in rows], marker="o", markersize=3,
                 color=BLUE, label="適合率（precision）")
    axes[1].plot(thresholds, [row["recall"] for row in rows], marker="s", markersize=3,
                 color=RED, label="再現率（recall）")
    axes[1].axvline(chosen["threshold"], color=GREEN, linestyle=":")
    axes[1].set_xlabel("閾値")
    axes[1].set_ylabel("割合")
    axes[1].set_ylim(0, 1)
    axes[1].set_title("適合率と再現率は逆に動く")
    axes[1].legend(fontsize=9)

    return save_figure(fig, FIGURES[1])


def draw_leak_check() -> Path:
    """図3: 増分実験の PR-AUC。リークを混ぜた段階だけが跳ねることを 1 枚で示す。"""
    results = run_steps(add_all_features(load_order_table()))
    base_pr = next(result["pr_auc"] for result in results if result["key"] == "②")

    labels = [str(index) for index, _ in enumerate(results, start=1)]  # 1〜7 = ①〜⑦
    values = [result["pr_auc"] for result in results]
    colors = [RED if result["key"] == "⑦" else BLUE for result in results]

    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    bars = ax.bar(labels, values, color=colors)
    ax.bar_label(bars, fmt="%.4f", fontsize=9)
    ax.axhline(base_pr, color=GRAY, linestyle="--", label=f"基準モデル②（PR-AUC {base_pr:.4f}）")
    ax.set_ylim(0, 0.6)
    ax.set_xlabel("増分実験の段階（1 = ①素の3列 … 7 = ⑦全期間のキャンセル数）")
    ax.set_ylabel("PR-AUC")
    ax.set_title("特徴量を足したときの PR-AUC（赤い 7 だけがリーク）")
    ax.legend(fontsize=9)
    return save_figure(fig, FIGURES[2])


def main() -> None:
    for path in (draw_pr_curve(), draw_threshold_tradeoff(), draw_leak_check()):
        print(f"図を保存しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
