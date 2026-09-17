"""閾値は業務が決める ― 見逃しと誤検出の重みから最適な閾値を探す。

使い方:
    docker compose exec lab python src/session20/threshold_by_cost.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    COST_SETTINGS,
    best_cost_threshold,
    cost_table,
    fit_high_rating,
    load_review_table,
    print_threshold_table,
    save_figure,
    threshold_table,
)

FIGURE_NAME = "s20_cost_threshold.png"


def draw(y_true, proba, path_name: str):
    """コストの重みごとに「閾値 → 総コスト」の曲線を描き、最小の点に印を付ける。"""
    fig, axes = plt.subplots(1, len(COST_SETTINGS), figsize=(12, 3.8))
    for ax, (miss_cost, alarm_cost) in zip(axes, COST_SETTINGS):
        table = cost_table(y_true, proba, miss_cost, alarm_cost)
        best = best_cost_threshold(y_true, proba, miss_cost, alarm_cost)
        ax.plot(table["threshold"], table["total_cost"], marker="o", markersize=3, color="#4c78a8")
        ax.scatter([best["threshold"]], [best["total_cost"]], color="#e45756", zorder=5)
        ax.set_title(f"見逃し : 誤検出 = {miss_cost} : {alarm_cost}（最小は閾値 {best['threshold']:.2f}）")
        ax.set_xlabel("閾値")
        ax.set_ylabel("総コスト")
    fig.tight_layout()
    path = save_figure(fig, path_name)
    plt.close(fig)
    return path


def main() -> None:
    df = load_review_table()
    y_test, proba = fit_high_rating(df)

    print("■ 閾値を動かすと指標はこう動く（セッション17 の再掲）")
    print_threshold_table(threshold_table(y_test, proba))
    print()

    print("■ 業務のコストから閾値を決める（0.05 刻みで総コストが最小の閾値を探す）")
    for miss_cost, alarm_cost in COST_SETTINGS:
        best = best_cost_threshold(y_test, proba, miss_cost, alarm_cost)
        print(
            f"見逃し : 誤検出 = {miss_cost} : {alarm_cost} → 閾値 {best['threshold']:.2f}"
            f"（総コスト {best['total_cost']:,.0f}）"
        )
    print()

    path = draw(y_test, proba, FIGURE_NAME)
    print(f"図を保存しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
