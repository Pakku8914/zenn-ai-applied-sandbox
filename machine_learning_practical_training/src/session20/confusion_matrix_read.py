"""混同行列の 4 象限を作り、そこから適合率・再現率・F1 を計算する。

使い方:
    docker compose exec lab python src/session20/confusion_matrix_read.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from common import (
    DEFAULT_THRESHOLD,
    average_scores,
    class_metrics,
    confusion_parts,
    fit_high_rating,
    load_review_table,
    POSITIVE_LABEL,
    predict_at,
    print_confusion,
    save_figure,
)

FIGURE_NAME = "s20_confusion.png"


def draw(parts: dict[str, int], path_name: str):
    """左に件数、右に行ごとの割合（= クラスごとの再現率）を描く。"""
    counts = np.array([[parts["tn"], parts["fp"]], [parts["fn"], parts["tp"]]], dtype="float64")
    ratios = counts / counts.sum(axis=1, keepdims=True)
    labels = np.array([["TN", "FP"], ["FN", "TP"]])

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for ax, matrix, title, fmt in [
        (axes[0], counts, "件数（閾値 0.5）", "{:,.0f}"),
        (axes[1], ratios, "行ごとの割合（= クラスごとの再現率）", "{:.4f}"),
    ]:
        ax.imshow(ratios, cmap="Blues", vmin=0.0, vmax=1.0)
        for i in range(2):
            for j in range(2):
                ax.text(
                    j,
                    i,
                    f"{labels[i, j]}\n{fmt.format(matrix[i, j])}",
                    ha="center",
                    va="center",
                    fontsize=13,
                    color="#222222" if ratios[i, j] < 0.6 else "#ffffff",
                )
        ax.set_xticks([0, 1], ["予測: 低評価", "予測: 高評価"])
        ax.set_yticks([0, 1], ["実測: 低評価", "実測: 高評価"])
        ax.set_title(title)
    fig.tight_layout()
    path = save_figure(fig, path_name)
    plt.close(fig)
    return path


def main() -> None:
    df = load_review_table()
    y_test, proba = fit_high_rating(df)
    y_pred = predict_at(proba, DEFAULT_THRESHOLD)
    parts = confusion_parts(y_test, y_pred)

    n_positive = int((y_test == POSITIVE_LABEL).sum())
    print("■ 評価データの内訳")
    print(f"評価データ {len(y_test):,} 件 / 高評価（陽性）{n_positive:,} 件 / 低評価（陰性）{len(y_test) - n_positive:,} 件")
    print(f"正例率: {y_test.mean():.4f}")
    print()

    print(f"■ 閾値 {DEFAULT_THRESHOLD} の混同行列")
    print_confusion(parts)
    print()

    print("■ 4 象限の呼び名と件数")
    print(f"TN（低評価と言って、実際に低評価だった）  : {parts['tn']:,} 件")
    print(f"FP（高評価と言ったが、実は低評価だった）  : {parts['fp']:,} 件")
    print(f"FN（低評価と言ったが、実は高評価だった）  : {parts['fn']:,} 件")
    print(f"TP（高評価と言って、実際に高評価だった）  : {parts['tp']:,} 件")
    print()

    # 式どおりに手で計算した値と、sklearn が返す値が一致することを確かめる
    precision = parts["tp"] / (parts["tp"] + parts["fp"])
    recall = parts["tp"] / (parts["tp"] + parts["fn"])
    f1 = 2 * precision * recall / (precision + recall)
    sklearn_metrics = class_metrics(y_test, y_pred, POSITIVE_LABEL)
    scores = average_scores(y_test, y_pred)

    print("■ 陽性クラス（高評価）の指標 ― 式と sklearn の一致")
    print(
        f"適合率 = TP / (TP + FP) = {parts['tp']:,} / {parts['tp'] + parts['fp']:,} = {precision:.4f}"
        f"（sklearn {sklearn_metrics['precision']:.4f}）"
    )
    print(
        f"再現率 = TP / (TP + FN) = {parts['tp']:,} / {parts['tp'] + parts['fn']:,} = {recall:.4f}"
        f"（sklearn {sklearn_metrics['recall']:.4f}）"
    )
    print(f"F1 = 2 * 適合率 * 再現率 / (適合率 + 再現率) = {f1:.4f}（sklearn {sklearn_metrics['f1']:.4f}）")
    print(
        f"accuracy = (TN + TP) / 全件 = {parts['tn'] + parts['tp']:,} / {len(y_test):,}"
        f" = {scores['accuracy']:.4f}"
    )
    print()

    path = draw(parts, FIGURE_NAME)
    print(f"図を保存しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
