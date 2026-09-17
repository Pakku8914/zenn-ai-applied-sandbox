"""問題5: Ridge と Lasso を α 4 段階で比べ、表と図にまとめる。

使い方:
    docker compose exec lab python src/session16/q5_regularization_table.py
"""

from __future__ import annotations

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.linear_model import Lasso, Ridge

from common import (
    LABEL_JA,
    LASSO_ALPHAS,
    OUT_DIR,
    RIDGE_ALPHAS,
    coef_series,
    fit_linear,
    fit_penalized,
    load_rated_reviews,
    regression_scores,
    split_xy,
    standardize,
    zero_columns,
)


def penalty_table(maker, alphas, X_train_s, y_train, X_test_s, y_test) -> pd.DataFrame:
    """α ごとに「係数・非ゼロの数・評価データの R2」を集めた表を作る。"""
    rows = []
    for alpha in alphas:
        coefs, r2 = fit_penalized(maker(alpha), X_train_s, y_train, X_test_s, y_test)
        zeros = zero_columns(coefs)
        rows.append(
            {
                "alpha": alpha,
                "price": float(coefs["price"]),
                "n_nonzero": len(coefs) - len(zeros),
                "zeros": zeros,
                "r2": r2,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    df = load_rated_reviews()
    X_train, X_test, y_train, y_test = split_xy(df)
    X_train_s, X_test_s, _ = standardize(X_train, X_test)

    plain = fit_linear(X_train_s, y_train)
    plain_coefs = coef_series(plain, X_train_s.columns)
    print("■ 正則化なし（基準）")
    print(f"price の係数 {plain_coefs['price']:+.4f} / R2 {regression_scores(plain, X_test_s, y_test)['r2']:.4f}")

    ridge = penalty_table(lambda a: Ridge(alpha=a), RIDGE_ALPHAS, X_train_s, y_train, X_test_s, y_test)
    print("\n■ Ridge")
    for _, row in ridge.iterrows():
        print(f"α = {row['alpha']:>6} : price の係数 {row['price']:+.4f} / 非ゼロ {int(row['n_nonzero'])} 個 / R2 {row['r2']:.4f}")
    print(f"どの α でもゼロになった列が無いか : {bool((ridge['n_nonzero'] == 4).all())}")

    lasso = penalty_table(lambda a: Lasso(alpha=a), LASSO_ALPHAS, X_train_s, y_train, X_test_s, y_test)
    print("\n■ Lasso")
    for _, row in lasso.iterrows():
        print(f"α = {row['alpha']:>6} : 非ゼロ {int(row['n_nonzero'])} 個 / ゼロになった列 {row['zeros']} / R2 {row['r2']:.4f}")
    print(f"最初にゼロになった列 : {lasso.loc[1, 'zeros']}")

    strongest = Lasso(alpha=1.0).fit(X_train_s, y_train)
    print(f"α = 1.0 の予測が訓練データの星の平均と一致するか : {bool(np.allclose(strongest.predict(X_test_s), y_train.mean()))}")

    # 図：Ridge と Lasso で、同じ α の並びに対する 4 つの係数の動きを比べる
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    alphas = np.logspace(-3, 2, 15)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
    for ax, maker, title in [
        (axes[0], lambda a: Ridge(alpha=a), "Ridge"),
        (axes[1], lambda a: Lasso(alpha=a), "Lasso"),
    ]:
        paths = {name: [] for name in X_train_s.columns}
        for alpha in alphas:
            coefs, _ = fit_penalized(maker(alpha), X_train_s, y_train, X_test_s, y_test)
            for name in paths:
                paths[name].append(float(coefs[name]))
        for name, values in paths.items():
            ax.plot(alphas, values, marker=".", label=LABEL_JA[name])
        ax.set_xscale("log")
        ax.axhline(0, color="#333333", linewidth=0.8)
        ax.set_title(f"{title}（α を上げたときの係数）")
        ax.set_xlabel("α")
    axes[0].set_ylabel("標準化後の係数")
    axes[1].legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "s16_q5_regularization.png", dpi=110)
    plt.close(fig)
    print("\n図を保存しました: outputs/s16_q5_regularization.png")

    print("\n■ 判断")
    print("この場面では Ridge はほとんど効きません。特徴量が 4 つしかなく、サンプルが 1 万件以上あるため、")
    print("係数はもともと安定していて縮める必要がないからです。正則化が効くのは、特徴量が多くて")
    print("サンプルが少ない（係数が過学習しやすい）場面です。")


if __name__ == "__main__":
    main()
