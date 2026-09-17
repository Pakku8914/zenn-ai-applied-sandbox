"""本文 6 節: 評価データの 1 件を星 10 に差し替えて、指標の頑健さを比べる。

RMSE は誤差を二乗するので 1 件の外れ値に大きく動き、MAE はほとんど動きません。
「どちらが正しいか」ではなく「どちらの性格が業務に合うか」の話です。
"""

from __future__ import annotations

import matplotlib.pyplot as plt

from common import LGBM, OUTLIER_STAR, fit_predict_all, regression_scores, save_figure


def draw(before: dict[str, float], after: dict[str, float], filename: str = "s21_outlier_effect.png"):
    """差し替えの前後で MAE と RMSE がどれだけ動いたかを並べる。"""
    fig, ax = plt.subplots(figsize=(7, 4.2))
    labels = ["MAE", "RMSE"]
    positions = range(len(labels))
    width = 0.35
    ax.bar([p - width / 2 for p in positions], [before["mae"], before["rmse"]], width, label="差し替え前")
    ax.bar([p + width / 2 for p in positions], [after["mae"], after["rmse"]], width, label="差し替え後")
    ax.set_xticks(list(positions), labels)
    ax.set_ylabel("指標の値（星）")
    ax.set_title("外れ値 1 件を入れたときの指標の動き")
    ax.legend()
    return save_figure(fig, filename)


def main() -> None:
    y_test, preds = fit_predict_all()
    pred = preds[LGBM]

    y_outlier = y_test.copy()  # 元の評価データは壊さない
    original = float(y_outlier.iloc[0])
    y_outlier.iloc[0] = OUTLIER_STAR  # 5 段階のはずの星に 10 が混ざった、という想定

    print("■ 評価データの先頭 1 件だけを星 10 に差し替える")
    print(f"差し替えた行の実測: {original:.1f} → {OUTLIER_STAR:.1f}")
    print(f"差し替えた行の予測: {pred[0]:.4f}")
    print()

    before = regression_scores(y_test, pred)
    after = regression_scores(y_outlier, pred)
    mae_delta = after["mae"] - before["mae"]
    rmse_delta = after["rmse"] - before["rmse"]

    print("■ 指標の変化（LightGBM）")
    print(f"MAE : {before['mae']:.4f} → {after['mae']:.4f}（{mae_delta:+.4f}）")
    print(f"RMSE: {before['rmse']:.4f} → {after['rmse']:.4f}（{rmse_delta:+.4f}）")
    print(f"RMSE の増え方は MAE の増え方の何倍か: {rmse_delta / mae_delta:.2f}")
    print(f"RMSE のほうが外れ値に敏感か: {rmse_delta > mae_delta}")
    print(f"MAE は元の値の 1% 以上動いたか: {mae_delta / before['mae'] >= 0.01}")
    print()

    draw(before, after)


if __name__ == "__main__":
    main()
