"""問題6 の解答: 業務要件から指標を選び、選んだ指標での 1 位を突き合わせる。

「MAE を要件にすると、特徴量を 1 つも使わないモデルが採用される」ことが結論です。
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import mean_absolute_percentage_error

from common import (
    LGBM,
    MEAN,
    MODEL_ORDER,
    RANDOM_STATE,
    best_model,
    fit_predict_all,
    save_figure,
    score_all,
)

TOLERANCE = 0.5  # 「だいたい当たった」とみなす幅（星）

# (要件の文, 選ぶ指標) の対応。指標は要件から決まるもので、結果を見てから選ばない
REQUIREMENTS = [
    ("平均してどれくらいずれるかを星の単位で説明したい", "mae"),
    ("星 5 の本を星 3 と予測する大外しを何より避けたい", "rmse"),
    ("モデルを作った価値があったかを経営に説明したい", "r2"),
]


def format_metric(metric: str, value: float) -> str:
    """R2 だけは符号を付けて表示する（負になりうる指標だから）。"""
    return f"{value:+.4f}" if metric == "r2" else f"{value:.4f}"


def within_tolerance(y_true, pred, tolerance: float = TOLERANCE) -> float:
    """予測が実測の ±tolerance に入った割合。業務説明でよく使う。"""
    error = np.abs(np.asarray(y_true, dtype="float64") - np.asarray(pred, dtype="float64"))
    return float(np.mean(error <= tolerance))


def mape_with_zero(y_true, pred) -> float:
    """実測を 1 件だけ 0.0 にしたときの MAPE（ゼロ割りの実演）。"""
    y_zero = y_true.copy()
    y_zero.iloc[0] = 0.0
    return float(mean_absolute_percentage_error(y_zero, pred))


def draw(y_true, pred, filename: str = "s21_q6_pred_vs_actual.png"):
    """実測と予測の散布図に「±0.5 の帯」を重ねる。"""
    rng = np.random.default_rng(RANDOM_STATE)  # 何度実行しても同じ図になる
    jitter = rng.uniform(-0.18, 0.18, len(pred))
    line = np.linspace(1, 5, 100)

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.fill_between(line, line - TOLERANCE, line + TOLERANCE, color="orange", alpha=0.2, label="±0.5 の帯")
    ax.plot(line, line, color="gray", linestyle="--", linewidth=1.2, label="予測 = 実測")
    ax.scatter(np.asarray(y_true, dtype="float64") + jitter, pred, s=6, alpha=0.12, color="#1f77b4")
    ax.set_xlabel("実測の星（横方向に少し散らしてある）")
    ax.set_ylabel("予測した星")
    ax.set_title("実測と予測（LightGBM）と許容幅")
    ax.set_xlim(0.5, 5.5)
    ax.set_ylim(0.5, 5.5)
    ax.legend(loc="upper left")
    return save_figure(fig, filename)


def main() -> None:
    y_test, preds = fit_predict_all()
    scores = score_all(y_test, preds)

    print(f"■ 業務要件ごとに選ぶ指標と、その指標での 1 位（評価データ {len(y_test):,} 件）")
    for index, (text, metric) in enumerate(REQUIREMENTS, start=1):
        winner = best_model(scores, metric)
        print(f"要件{index}: {text}")
        print(f"  → 選ぶ指標 {metric.upper()} / 1 位 {winner}（{format_metric(metric, scores[winner][metric])}）")
    print()

    mae_winner = best_model(scores, "mae")
    print("■ 要件1 の結論をそのまま採用すると")
    print(f"採用するモデル: {mae_winner}")
    print(f"そのモデルは特徴量を 1 つも使っていないか: {mae_winner == MEAN}")
    print()

    print(f"■ 予測が実測の ±{TOLERANCE} に入った割合（業務でよく使う言い方）")
    for name in MODEL_ORDER:
        print(f"{name}: {within_tolerance(y_test, preds[name]):.2%}")
    print()

    broken = mape_with_zero(y_test, preds[LGBM])
    print("■ MAPE を使ってよいか")
    print(f"評価データの星の最小値: {y_test.min():.1f}（0 より大きいので計算はできる）")
    print(f"実測を 1 件だけ 0.0 に差し替えたときの MAPE: {broken:.3e}")
    print(f"その MAPE は 1,000,000 を超えたか: {broken > 1e6}")
    print()

    draw(y_test, preds[LGBM])


if __name__ == "__main__":
    main()
