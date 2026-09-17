"""問題6 の解答: キャリブレーションを確認し、報告すべき指標のセットを関数にする。

実行:
    docker compose exec lab python src/session24/q6_report_card.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    CALIBRATION_BINS,
    calibration_gap,
    calibration_points,
    cancel_probabilities,
    print_calibration,
    print_report_card,
    report_card,
    save_figure,
    threshold_table,
)

FIGURE_NAME = "s24_q6_calibration.png"
# この閾値で運用すると決めた（問題3 で選んだ値）
OPERATING_THRESHOLD = 0.2

CHECKLIST = [
    "正例率と件数を書いたか（PR-AUC はこれを読まないと解釈できない）",
    "PR-AUC を書いたか（ROC AUC だけで判断していないか）",
    "運用する閾値と、そのときの適合率・再現率・混同行列を書いたか",
    "Brier スコアと予測確率の平均を書いたか（確率として使うなら必須）",
    "accuracy を報告から外したか（ベースラインと同じ値になる）",
]


def analyze() -> dict[str, object]:
    """報告カードと、2 つのモデルのキャリブレーションをまとめる。"""
    y_test, plain = cancel_probabilities("plain")
    _, under = cancel_probabilities("under")
    plain_pred, plain_true = calibration_points(y_test, plain)
    under_pred, under_true = calibration_points(y_test, under)
    return {
        "card": report_card(y_test, plain, OPERATING_THRESHOLD),
        "plain_curve": (plain_pred, plain_true),
        "under_curve": (under_pred, under_true),
        "plain_gap": calibration_gap(y_test, plain),
        "under_gap": calibration_gap(y_test, under),
        "rows": threshold_table(y_test, plain),
    }


def draw(result: dict[str, object], path_name: str):
    """2 つのキャリブレーション曲線を 1 枚に重ねる（対角線が理想）。"""
    plain_pred, plain_true = result["plain_curve"]
    under_pred, under_true = result["under_curve"]

    fig, ax = plt.subplots(figsize=(6, 4.6))
    ax.plot([0, 1], [0, 1], color="#888888", linestyle="--", linewidth=1, label="理想（予測 = 実績）")
    ax.plot(plain_pred, plain_true, marker="o", color="#4c78a8", label="重みなし")
    ax.plot(under_pred, under_true, marker="s", color="#e45756", label="1:1 アンダーサンプリング")
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.set_title("キャリブレーション曲線（5 分位）")
    ax.set_xlabel("予測確率の平均")
    ax.set_ylabel("実際にキャンセルされた割合")
    ax.legend(loc="upper left", fontsize=8)

    fig.tight_layout()
    path = save_figure(fig, path_name)
    plt.close(fig)
    return path


def main() -> None:
    result = analyze()

    print(f"■ 1. キャリブレーション曲線（{CALIBRATION_BINS} 分位）")
    print("重みなし")
    print_calibration(*result["plain_curve"])
    print("1:1 アンダーサンプリング")
    print_calibration(*result["under_curve"])
    print()

    print("■ 2. ずれの大きさ（小数第 2 位まで）")
    print(f"重みなし              : {result['plain_gap']:.2f}")
    print(f"1:1 アンダーサンプリング: {result['under_gap']:.2f}")
    print()

    print("■ 3. 報告カード")
    print_report_card(result["card"], "LightGBM・重みなし・閾値 0.2")
    print()

    print("■ 4. チェックリスト")
    for index, item in enumerate(CHECKLIST, start=1):
        print(f"{index}. {item}")
    print()

    path = draw(result, FIGURE_NAME)
    print(f"図を保存しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
