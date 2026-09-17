"""ROC 曲線と PR 曲線を並べて描き、2 つの AUC の乖離を確かめる。

使い方:
    docker compose exec lab python src/session24/roc_vs_pr.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    baseline_scores,
    cancel_probabilities,
    pr_points,
    roc_points,
    save_figure,
    score_summary,
)

FIGURE_NAME = "s24_roc_pr.png"


def draw(y_true, proba, path_name: str):
    """左に ROC 曲線、右に PR 曲線。どちらにも「でたらめの線」を入れる。"""
    fpr, tpr, _ = roc_points(y_true, proba)
    precision, recall, _ = pr_points(y_true, proba)
    scores = score_summary(y_true, proba)
    base = baseline_scores(y_true)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))

    axes[0].plot(fpr, tpr, color="#4c78a8", label=f"ROC AUC {scores['roc_auc']:.4f}")
    axes[0].plot([0, 1], [0, 1], color="#888888", linestyle="--", linewidth=1, label="でたらめ（AUC 0.5000）")
    axes[0].set_title("ROC 曲線（見栄えがする）")
    axes[0].set_xlabel("FPR ＝ 誤検出の割合（分母は 14,467 件）")
    axes[0].set_ylabel("TPR ＝ 再現率")
    axes[0].legend(loc="lower right", fontsize=8)

    axes[1].plot(recall, precision, color="#e45756", label=f"PR-AUC {scores['pr_auc']:.4f}")
    axes[1].axhline(
        base["positive_rate"],
        color="#888888",
        linestyle="--",
        linewidth=1,
        label=f"でたらめ ＝ 正例率 {base['positive_rate']:.4f}",
    )
    axes[1].set_ylim(0.0, 1.0)
    axes[1].set_title("PR 曲線（同じモデル・同じ確率）")
    axes[1].set_xlabel("再現率")
    axes[1].set_ylabel("適合率")
    axes[1].legend(loc="upper right", fontsize=8)

    fig.tight_layout()
    path = save_figure(fig, path_name)
    plt.close(fig)
    return path


def main() -> None:
    y_test, proba = cancel_probabilities("plain")
    scores = score_summary(y_test, proba)
    base = baseline_scores(y_test)

    print("■ 順位を付ける力（閾値に依存しない 2 つの指標）")
    print(f"ROC AUC : {scores['roc_auc']:.4f}（でたらめ {base['roc_auc']:.4f}）")
    print(f"PR-AUC  : {scores['pr_auc']:.4f}（でたらめ ＝ 正例率 {base['pr_auc']:.4f}）")
    print()

    print("■ でたらめからの伸び（小数第 3 位まで）")
    print(f"ROC AUC : {scores['roc_auc'] - base['roc_auc']:+.3f}")
    print(f"PR-AUC  : {scores['pr_auc'] - base['pr_auc']:+.3f}")
    print()

    print("■ 参考: セッション20 の高評価分類（正例率 0.8167）では順序が逆になった")
    print("ROC AUC 0.8265 < PR-AUC 0.9554（正例が多数派なら PR-AUC のほうが高く出る）")
    print()

    path = draw(y_test, proba, FIGURE_NAME)
    print(f"図を保存しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
