"""statsmodels で係数の p 値と 95% 信頼区間を読む（scikit-learn が出してくれないもの）。

使い方:
    docker compose exec lab python src/session16/ols_inference.py
"""

from __future__ import annotations

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    FEATURES,
    LABEL_JA,
    OUT_DIR,
    coef_series,
    fit_linear,
    fit_ols,
    load_rated_reviews,
    split_xy,
    standardize,
)


def format_p(p: float) -> str:
    """小さすぎる p 値は指数表記で、そうでなければ小数で表示する。"""
    return f"{p:.2e}" if p < 0.001 else f"{p:.4f}"


def main() -> None:
    df = load_rated_reviews()
    X_train, X_test, y_train, y_test = split_xy(df)

    result = fit_ols(X_train, y_train)  # 切片の列は fit_ols の中で add_constant している
    print("■ statsmodels の最小二乗法（訓練データ）")
    print(f"観測数 {int(result.nobs):,} 件 / R2 {result.rsquared:.4f} / 調整済み R2 {result.rsquared_adj:.4f}")

    print("\n■ 係数と p 値")
    for name in FEATURES:
        print(f"{name:<15}: {result.params[name]:+.6f} / p 値 {format_p(float(result.pvalues[name]))}")
    significant = [name for name in FEATURES if result.pvalues[name] < 0.05]
    print(f"p < 0.05 だった列 : {significant}")

    print("\n■ 95% 信頼区間")
    # conf_int() は行が列名、1 列目が下限・2 列目が上限。列名に頼らず位置で取り出す
    conf = result.conf_int()
    low, high = float(conf.loc["price"].iloc[0]), float(conf.loc["price"].iloc[1])
    print(f"price          : [{low:+.6f}, {high:+.6f}]（幅 {high - low:.6f}）")
    py_low = float(conf.loc["published_year"].iloc[0])
    py_high = float(conf.loc["published_year"].iloc[1])
    print(f"published_year の区間が 0 をまたぐか : {bool(py_low < 0 < py_high)}")

    print("\n■ scikit-learn は同じ係数を出すが、確かさは教えてくれない")
    sk_model = fit_linear(X_train, y_train)
    sk_coefs = coef_series(sk_model, X_train.columns)
    same = bool(np.allclose(sk_coefs.to_numpy(), result.params[FEATURES].to_numpy()))
    print(f"LinearRegression と statsmodels の係数が一致するか : {same}")
    print(f"LinearRegression に p 値の属性があるか : {hasattr(sk_model, 'pvalues')}")

    # 図：標準化した係数に 95% 信頼区間を付けて描くと、0 をまたぐ列が一目で分かる
    X_train_s, _, _ = standardize(X_train, X_test)
    std_result = fit_ols(X_train_s, y_train)
    std_conf = std_result.conf_int()
    labels = [LABEL_JA[name] for name in FEATURES]
    centers = np.array([float(std_result.params[name]) for name in FEATURES])
    errors = np.array([float(std_conf.loc[name].iloc[1] - std_result.params[name]) for name in FEATURES])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    positions = np.arange(len(FEATURES))  # 文字列を軸に直接渡さず、位置とラベルを分けて指定する
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.errorbar(centers, positions, xerr=errors, fmt="o", color="#4c78a8", capsize=4)
    ax.axvline(0, color="#d62728", linestyle="--", linewidth=1.0, label="効果ゼロの線")
    ax.set_yticks(positions, labels)
    ax.set_title("標準化した係数と 95% 信頼区間（訓練データ）")
    ax.set_xlabel("1 標準偏差ぶん動いたときの星の変化")
    ax.legend(loc="lower left", fontsize=8)
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "s16_conf_int.png", dpi=110)
    plt.close(fig)
    print("\n図を保存しました: outputs/s16_conf_int.png")


if __name__ == "__main__":
    main()
