"""閾値を下げると適合率と再現率がどう動くかを表と図で確かめる。

使い方:
    docker compose exec lab python src/session24/threshold_sweep.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    THRESHOLD_GRID,
    best_f1_row,
    cancel_probabilities,
    print_threshold_table,
    save_figure,
    threshold_table,
)

FIGURE_NAME = "s24_threshold.png"


def draw(y_true, proba, path_name: str):
    """細かい刻みで適合率・再現率・F1 を描き、表に載せた 4 点に印を付ける。"""
    grid = threshold_table(y_true, proba, THRESHOLD_GRID)
    marks = threshold_table(y_true, proba)
    x = [row["threshold"] for row in grid]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))

    axes[0].plot(x, [row["precision"] for row in grid], color="#4c78a8", label="適合率")
    axes[0].plot(x, [row["recall"] for row in grid], color="#e45756", label="再現率")
    axes[0].plot(x, [row["f1"] for row in grid], color="#54a24b", linestyle="--", label="F1")
    axes[0].scatter(
        [row["threshold"] for row in marks],
        [row["f1"] for row in marks],
        color="#54a24b",
        zorder=5,
        label="表に載せた閾値",
    )
    axes[0].set_title("閾値と 3 つの指標")
    axes[0].set_xlabel("閾値")
    axes[0].set_ylabel("指標の値")
    axes[0].legend(loc="upper center", fontsize=8)

    axes[1].plot(x, [row["n_positive"] for row in grid], color="#9d755d", label="陽性と予測した件数")
    axes[1].plot(x, [row["tp"] for row in grid], color="#e45756", label="うち本当のキャンセル（TP）")
    axes[1].set_title("閾値と件数（陽性と予測した数はすぐに枯れる）")
    axes[1].set_xlabel("閾値")
    axes[1].set_ylabel("件数")
    axes[1].legend(loc="upper right", fontsize=8)

    fig.tight_layout()
    path = save_figure(fig, path_name)
    plt.close(fig)
    return path


def main() -> None:
    y_test, proba = cancel_probabilities("plain")
    rows = threshold_table(y_test, proba)

    print("■ 閾値を下げると何が起きるか（評価データ 15,008 件・実際のキャンセル 541 件）")
    print_threshold_table(rows)
    print()

    best = best_f1_row(rows)
    print(f"F1 がいちばん高い閾値: {best['threshold']:.1f}（F1 {best['f1']:.4f}）")
    print("※ F1 は適合率と再現率を同じ重さで見る指標です。業務の重みが違うなら F1 で選ばないでください。")
    print()

    path = draw(y_test, proba, FIGURE_NAME)
    print(f"図を保存しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
