"""問題4 の解答: 残差を要約・可視化して、モデルの系統的な偏りを見つける。"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

from common import (
    LGBM,
    STARS,
    fit_predict_all,
    residual_by_actual,
    residual_summary,
    residual_table,
    residuals,
    save_figure,
)

BIG_RESIDUAL = 1.0  # 「大きく外した」とみなす残差の大きさ（星 1 つぶん）


def diagnose(y_true, pred) -> dict[str, float]:
    """残差の要約に「大きく外した件数と割合」を足す。"""
    res = residuals(y_true, pred)
    summary = residual_summary(res)
    big = int(np.sum(np.abs(res) > BIG_RESIDUAL))
    summary["big_count"] = float(big)
    summary["big_ratio"] = big / len(res)
    return summary


def worst_star(grouped) -> tuple[float, float]:
    """残差の平均の絶対値がいちばん大きい星と、その値を返す。"""
    means = grouped.loc[STARS, "residual_mean"]
    star = float(means.abs().idxmax())
    return star, float(means.loc[star])


def draw(table, filename: str = "s21_q4_residual_hist.png"):
    """左: 残差全体のヒストグラム / 右: 実測の星ごとに重ねたヒストグラム。"""
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))

    axes[0].hist(table["residual"], bins=40, color="#1f77b4")
    axes[0].axvline(0, color="gray", linestyle="--", linewidth=1.2, label="残差 0")
    axes[0].axvline(table["residual"].mean(), color="crimson", linewidth=1.4, label="残差の平均")
    axes[0].set_xlabel("残差（実測 − 予測）")
    axes[0].set_ylabel("件数")
    axes[0].set_title("残差の分布（全体）")
    axes[0].legend()

    for star in STARS:
        values = table.loc[table["actual"] == star, "residual"]
        axes[1].hist(values, bins=30, histtype="step", linewidth=1.6, label=f"実測 星 {star:.0f}")
    axes[1].axvline(0, color="gray", linestyle="--", linewidth=1.2)
    axes[1].set_xlabel("残差（実測 − 予測）")
    axes[1].set_ylabel("件数")
    axes[1].set_title("実測の星ごとの残差の分布")
    axes[1].legend()

    return save_figure(fig, filename)


def main() -> None:
    y_test, preds = fit_predict_all()
    pred = preds[LGBM]
    summary = diagnose(y_test, pred)

    print(f"■ 残差の要約（LightGBM・評価データ {len(y_test):,} 件）")
    print(f"平均: {summary['mean']:+.4f}")
    print(f"標準偏差: {summary['std']:.4f}")
    print(f"最大絶対値: {summary['max_abs']:.4f}")
    print(
        f"残差の絶対値が {BIG_RESIDUAL:.1f} を超えた件数:"
        f" {int(summary['big_count']):,} 件（{summary['big_ratio']:.2%}）"
    )
    print()

    grouped = residual_by_actual(y_test, pred)
    print("■ 実測の星ごとの残差の平均")
    for star in STARS:
        row = grouped.loc[star]
        print(f"星 {star:.1f} | 件数 {int(row['count']):,} 件 | 残差の平均 {row['residual_mean']:+.4f}")
    star, value = worst_star(grouped)
    print()

    print("■ 判定")
    print(f"残差の平均の絶対値がいちばん大きい星: {star:.1f}（{value:+.4f}）")
    print(f"残差全体の平均は 0.05 より小さいか: {abs(summary['mean']) < 0.05}")
    print(f"星ごとに見ると 0.5 を超える偏りがあるか: {abs(value) > 0.5}")
    draw(residual_table(y_test, pred))


if __name__ == "__main__":
    main()
