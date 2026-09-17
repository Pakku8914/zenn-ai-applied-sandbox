"""本文 5 節: 予測値と実測値の散布図から系統的な誤りを見つける。

実測は 1〜5 の 5 段階なのに、予測は狭い帯の中にしか出てきません。
「モデルが中央に寄せている」ことを図と数値で確かめます。
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

from common import (
    LGBM,
    RANDOM_STATE,
    STARS,
    fit_predict_all,
    residual_by_actual,
    residual_table,
    save_figure,
)


def draw(table, grouped, filename: str = "s21_pred_vs_actual.png"):
    """実測（横）と予測（縦）の散布図。実測が離散なので横方向に少し散らす。"""
    rng = np.random.default_rng(RANDOM_STATE)  # 何度実行しても同じ図になる
    jitter = rng.uniform(-0.18, 0.18, len(table))

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(table["actual"] + jitter, table["pred"], s=6, alpha=0.12, color="#1f77b4")
    ax.plot([1, 5], [1, 5], color="gray", linestyle="--", linewidth=1.2, label="完全に当たる線（予測 = 実測）")
    ax.plot(
        grouped.index,
        grouped["pred_mean"],
        color="crimson",
        marker="o",
        linewidth=1.6,
        label="実測の星ごとの予測の平均",
    )
    ax.set_xlabel("実測の星（横方向に少し散らしてある）")
    ax.set_ylabel("予測した星")
    ax.set_title("実測と予測（LightGBM・評価データ）")
    ax.set_xlim(0.5, 5.5)
    ax.set_ylim(0.5, 5.5)
    ax.legend(loc="upper left")

    return save_figure(fig, filename)


def main() -> None:
    y_test, preds = fit_predict_all()
    pred = preds[LGBM]
    table = residual_table(y_test, pred)

    actual_values = table["actual"].to_numpy()
    pred_values = table["pred"].to_numpy()
    print(f"■ 予測値と実測値の広がり（評価データ {len(table):,} 件）")
    print(
        f"実測: 最小 {actual_values.min():.4f} / 最大 {actual_values.max():.4f}"
        f" / 標準偏差 {actual_values.std():.4f}"
    )
    print(
        f"予測: 最小 {pred_values.min():.4f} / 最大 {pred_values.max():.4f}"
        f" / 標準偏差 {pred_values.std():.4f}"
    )
    narrower = (pred_values.max() - pred_values.min()) < (actual_values.max() - actual_values.min())
    print(f"予測の幅は実測の幅より狭いか: {narrower}")
    print(f"予測のばらつきは実測のばらつきより小さいか: {pred_values.std() < actual_values.std()}")
    print()

    grouped = residual_by_actual(y_test, pred)
    print("■ 実測の星ごとの予測の平均（モデルが返している答え）")
    for star in STARS:
        print(f"星 {star:.1f} | 予測の平均 {grouped.loc[star, 'pred_mean']:.4f}")
    gap = float(grouped.loc[5.0, "pred_mean"] - grouped.loc[3.0, "pred_mean"])
    print()
    print(f"■ 星 3 と星 5 に対する予測の平均の差: {gap:.4f}")
    print(f"（実測の差は 2.0 なのに、予測は {gap:.4f} しか離れていない）")
    draw(table, grouped.loc[STARS])


if __name__ == "__main__":
    main()
