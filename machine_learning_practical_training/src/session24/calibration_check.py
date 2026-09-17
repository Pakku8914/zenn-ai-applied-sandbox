"""キャリブレーション曲線を描き、確率が信じられる状態かどうかを確かめる。

使い方:
    docker compose exec lab python src/session24/calibration_check.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    CALIBRATION_BINS,
    baseline_scores,
    calibration_gap,
    calibration_points,
    cancel_probabilities,
    print_calibration,
    save_figure,
    score_summary,
)

FIGURE_NAME = "s24_calibration.png"


def draw(y_true, plain, under, path_name: str):
    """2 つのモデルのキャリブレーション曲線を 1 枚に重ねる（対角線が理想）。"""
    plain_pred, plain_true = calibration_points(y_true, plain)
    under_pred, under_true = calibration_points(y_true, under)
    rate = baseline_scores(y_true)["positive_rate"]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))

    for ax, limit, title in [
        (axes[0], 1.0, "全体（0 から 1 まで）"),
        (axes[1], 0.15, "左下を拡大（0 から 0.15 まで）"),
    ]:
        ax.plot([0, limit], [0, limit], color="#888888", linestyle="--", linewidth=1, label="理想（予測 = 実績）")
        ax.plot(plain_pred, plain_true, marker="o", color="#4c78a8", label="重みなし")
        ax.plot(under_pred, under_true, marker="s", color="#e45756", label="1:1 アンダーサンプリング")
        ax.axhline(rate, color="#54a24b", linestyle=":", linewidth=1, label=f"実際の正例率 {rate:.4f}")
        ax.set_xlim(0.0, limit)
        ax.set_ylim(0.0, limit)
        ax.set_title(title)
        ax.set_xlabel("予測確率の平均（5 分位）")
        ax.set_ylabel("実際にキャンセルされた割合")
        ax.legend(loc="upper left", fontsize=8)

    fig.tight_layout()
    path = save_figure(fig, path_name)
    plt.close(fig)
    return path


def main() -> None:
    y_test, plain = cancel_probabilities("plain")
    _, under = cancel_probabilities("under")

    print(f"■ キャリブレーション曲線（{CALIBRATION_BINS} 分位・strategy=\"quantile\"）")
    print("重みなし")
    print_calibration(*calibration_points(y_test, plain))
    print("1:1 アンダーサンプリング")
    print_calibration(*calibration_points(y_test, under))
    print()

    allowed = 0.05  # 「確率として使える」と判断する目安（業務によって決める）
    print("■ ずれの大きさ（|予測の平均 - 実際の割合| の最大・小数第 2 位まで）")
    for label, proba in [("重みなし              ", plain), ("1:1 アンダーサンプリング", under)]:
        gap = calibration_gap(y_test, proba)
        print(f"{label}: {gap:.2f}（{allowed} 以内か: {gap <= allowed}）")
    print()

    print("■ Brier スコア（小さいほど確率として正確）")
    print(f"重みなし              : {score_summary(y_test, plain)['brier']:.5f}")
    print(f"1:1 アンダーサンプリング: {score_summary(y_test, under)['brier']:.5f}")
    print()

    path = draw(y_test, plain, under, FIGURE_NAME)
    print(f"図を保存しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
