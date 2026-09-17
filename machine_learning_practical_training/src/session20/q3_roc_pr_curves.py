"""問題3 の解答：ROC 曲線と PR 曲線を描き、2 つの AUC を読み比べる。

使い方:
    docker compose exec lab python src/session20/q3_roc_pr_curves.py
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
)

FIGURE_NAME = "s20_q3_roc_pr.png"


def summary(y_true, proba) -> dict[str, float]:
    """問題3 で報告する値（2 つの AUC とそれぞれのベースライン）。"""
    scores = curve_scores(y_true, proba)
    base = baseline_scores(y_true)
    return {
        "roc_auc": scores["roc_auc"],
        "pr_auc": scores["pr_auc"],
        "positive_rate": scores["positive_rate"],
        "baseline_roc_auc": base["roc_auc"],
        "baseline_pr_auc": base["pr_auc"],
        "roc_gain": scores["roc_auc"] - base["roc_auc"],
        "pr_gain": scores["pr_auc"] - base["pr_auc"],
    }


def draw(y_true, proba, path_name: str):
    """ROC 曲線と PR 曲線を 1 枚に並べ、それぞれのベースラインも描く。"""
    fpr, tpr, _ = roc_points(y_true, proba)
    precision, recall, _ = pr_points(y_true, proba)
    values = summary(y_true, proba)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    axes[0].plot(fpr, tpr, color="#4c78a8", label=f"ROC AUC {values['roc_auc']:.4f}")
    axes[0].plot([0, 1], [0, 1], color="#888888", linestyle="--", linewidth=1, label="ベースライン 0.5000")
    axes[0].set_title("ROC 曲線")
    axes[0].set_xlabel("FPR")
    axes[0].set_ylabel("TPR")
    axes[0].legend(loc="lower right", fontsize=9)

    axes[1].plot(recall, precision, color="#54a24b", label=f"PR-AUC {values['pr_auc']:.4f}")
    axes[1].axhline(
        values["positive_rate"],
        color="#888888",
        linestyle="--",
        linewidth=1,
        label=f"ベースライン {values['positive_rate']:.4f}",
    )
    axes[1].set_ylim(0.0, 1.05)
    axes[1].set_title("PR 曲線")
    axes[1].set_xlabel("再現率")
    axes[1].set_ylabel("適合率")
    axes[1].legend(loc="lower left", fontsize=9)

    fig.tight_layout()
    path = save_figure(fig, path_name)
    plt.close(fig)
    return path


def main() -> None:
    df = load_review_table()
    y_test, proba = fit_high_rating(df)
    values = summary(y_test, proba)

    print("■ 2 つの AUC とベースライン")
    print(f"ROC AUC : {values['roc_auc']:.4f}（ベースライン {values['baseline_roc_auc']:.4f}）")
    print(f"PR-AUC  : {values['pr_auc']:.4f}（ベースライン {values['baseline_pr_auc']:.4f} ＝ 正例率）")
    print()

    print("■ ベースラインからの伸びで比べる")
    print(f"ROC AUC の伸び: {values['roc_gain']:+.4f}")
    print(f"PR-AUC の伸び : {values['pr_gain']:+.4f}")
    print(f"PR-AUC のほうが数字は大きいか: {values['pr_auc'] > values['roc_auc']}")
    print(f"ベースラインからの伸びも PR-AUC のほうが大きいか: {values['pr_gain'] > values['roc_gain']}")
    print()

    path = draw(y_test, proba, FIGURE_NAME)
    print(f"図を保存しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
