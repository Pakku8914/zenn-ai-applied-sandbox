"""本文 4 節: 残差プロットでモデルの不備を読む。

残差の平均はほぼ 0 なのに、実測の星ごとに見ると大きく偏っています。
「平均を見て安心しない」ことを図と数値の両方で確かめます。
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

from common import (
    LGBM,
    STARS,
    fit_predict_all,
    regression_scores,
    residual_by_actual,
    residual_summary,
    residual_table,
    residuals,
    save_figure,
)


def draw(table, filename: str = "s21_residual_plot.png"):
    """左: 予測値と残差の散布図 / 右: 実測の星ごとの残差の箱ひげ図。"""
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))

    axes[0].scatter(table["pred"], table["residual"], s=6, alpha=0.15, color="#1f77b4")
    axes[0].axhline(0, color="crimson", linewidth=1.2)
    axes[0].set_xlabel("予測した星")
    axes[0].set_ylabel("残差（実測 − 予測）")
    axes[0].set_title("残差プロット（LightGBM・評価データ）")

    groups = [table.loc[table["actual"] == star, "residual"].to_numpy() for star in STARS]
    axes[1].boxplot(groups, tick_labels=[f"星 {star:.0f}" for star in STARS])
    axes[1].axhline(0, color="crimson", linewidth=1.2)
    axes[1].set_ylabel("残差（実測 − 予測）")
    axes[1].set_title("実測の星ごとの残差の分布")

    return save_figure(fig, filename)


def main() -> None:
    y_test, preds = fit_predict_all()
    pred = preds[LGBM]
    res = residuals(y_test, pred)
    summary = residual_summary(res)

    print("■ LightGBM の残差（実測 − 予測）の要約")
    print(f"件数: {len(res)}")
    print(f"平均: {summary['mean']:+.4f}")
    print(f"標準偏差: {summary['std']:.4f}")
    print(f"最大絶対値: {summary['max_abs']:.4f}")
    rmse = regression_scores(y_test, pred)["rmse"]
    same = abs(float(np.sqrt(np.mean(res**2))) - rmse) < 1e-10
    print(f"残差の二乗平均の平方根が RMSE と一致するか: {same}")
    print()

    print("■ 実測の星ごとの残差の平均と予測の平均")
    grouped = residual_by_actual(y_test, pred)
    for star in STARS:
        row = grouped.loc[star]
        print(
            f"星 {star:.1f} | 件数 {int(row['count']):,} 件"
            f" | 残差の平均 {row['residual_mean']:+.4f}"
            f" | 予測の平均 {row['pred_mean']:.4f}"
        )
    print()

    print("■ 判定")
    print(f"残差の平均はほぼ 0 か（|平均| < 0.05）: {abs(summary['mean']) < 0.05}")
    sign_flip = grouped.loc[3.0, "residual_mean"] < 0 < grouped.loc[5.0, "residual_mean"]
    print(f"星 3 と星 5 で残差の符号が逆か: {sign_flip}")
    draw(residual_table(y_test, pred))


if __name__ == "__main__":
    main()
