"""ROC 曲線と PR 曲線を描き、2 つの AUC を読み比べる。

使い方:
    docker compose exec lab python src/session20/roc_pr_curves.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    baseline_scores,
    curve_scores,
    fit_high_rating,
    load_review_table,
    pr_points,
    roc_points,
    save_figure,
    youden_point,
)

FIGURE_NAME = "s20_roc_pr.png"


def draw(y_true, proba, path_name: str):
    """左に ROC 曲線（Youden の点つき）、右に PR 曲線（正例率の線つき）を描く。"""
    fpr, tpr, _ = roc_points(y_true, proba)
    precision, recall, _ = pr_points(y_true, proba)
    scores = curve_scores(y_true, proba)
    best = youden_point(y_true, proba)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))

    axes[0].plot(fpr, tpr, color="#4c78a8", label=f"ROC AUC {scores['roc_auc']:.4f}")
    axes[0].plot([0, 1], [0, 1], color="#888888", linestyle="--", linewidth=1, label="でたらめ（AUC 0.5000）")
    axes[0].scatter(
        [best["fpr"]],
        [best["tpr"]],
        color="#e45756",
        zorder=5,
        label=f"TPR - FPR が最大（閾値 {best['threshold']:.4f}）",
    )
    axes[0].set_title("ROC 曲線")
    axes[0].set_xlabel("FPR（低評価を高評価と言ってしまった割合）")
    axes[0].set_ylabel("TPR ＝ 再現率")
    axes[0].legend(loc="lower right", fontsize=8)

    axes[1].plot(recall, precision, color="#54a24b", label=f"PR-AUC {scores['pr_auc']:.4f}")
    axes[1].axhline(
        scores["positive_rate"],
        color="#888888",
        linestyle="--",
        linewidth=1,
        label=f"ベースライン ＝ 正例率 {scores['positive_rate']:.4f}",
    )
    axes[1].set_ylim(0.0, 1.05)
    axes[1].set_title("PR 曲線（適合率と再現率）")
    axes[1].set_xlabel("再現率")
    axes[1].set_ylabel("適合率")
    axes[1].legend(loc="lower left", fontsize=8)

    fig.tight_layout()
    path = save_figure(fig, path_name)
    plt.close(fig)
    return path


def main() -> None:
    df = load_review_table()
    y_test, proba = fit_high_rating(df)

    scores = curve_scores(y_test, proba)
    base = baseline_scores(y_test)
    print("■ 順位を付ける力（閾値に依存しない指標）")
    print(f"ROC AUC : {scores['roc_auc']:.4f}（ベースライン {base['roc_auc']:.4f}）")
    print(f"PR-AUC  : {scores['pr_auc']:.4f}（ベースライン ＝ 正例率 {base['pr_auc']:.4f}）")
    print()

    best = youden_point(y_test, proba)
    print("■ ROC 曲線の上で対角線からいちばん離れている点（Youden 指標 = TPR - FPR が最大）")
    print(f"閾値        : {best['threshold']:.4f}")
    print(f"TPR（再現率）: {best['tpr']:.4f}")
    print(f"FPR         : {best['fpr']:.4f}")
    print(f"TPR - FPR   : {best['youden']:.4f}")
    print()

    path = draw(y_test, proba, FIGURE_NAME)
    print(f"図を保存しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
