"""Ridge と Lasso ― 係数に「行き過ぎるな」と言う。α を数段階だけ手で試す。

使い方:
    docker compose exec lab python src/session16/regularization.py
"""

from __future__ import annotations

import matplotlib
import numpy as np

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

# 図に描くための細かい α（表は 4 段階だけにして、図はなめらかに見せる）
FINE_ALPHAS = np.logspace(-3, 3, 25)


def main() -> None:
    df = load_rated_reviews()
    X_train, X_test, y_train, y_test = split_xy(df)
    # 正則化は「係数の大きさ」に罰を与えるので、尺度をそろえないと不公平になる
    X_train_s, X_test_s, _ = standardize(X_train, X_test)

    plain = fit_linear(X_train_s, y_train)
    plain_coefs = coef_series(plain, X_train_s.columns)
    print("■ 正則化なし（比較の基準）")
    print(f"price の係数 {plain_coefs['price']:+.4f} / R2 {regression_scores(plain, X_test_s, y_test)['r2']:.4f}")

    print("\n■ Ridge ― 係数を小さくするが、ゼロにはしない")
    for alpha in RIDGE_ALPHAS:
        coefs, r2 = fit_penalized(Ridge(alpha=alpha), X_train_s, y_train, X_test_s, y_test)
        nonzero = len(coefs) - len(zero_columns(coefs))
        print(f"α = {alpha:>6} : price の係数 {coefs['price']:+.4f} / 非ゼロ {nonzero} 個 / R2 {r2:.4f}")

    print("\n■ Lasso ― 効いていない係数をちょうどゼロにする")
    for alpha in LASSO_ALPHAS:
        coefs, r2 = fit_penalized(Lasso(alpha=alpha), X_train_s, y_train, X_test_s, y_test)
        zeros = zero_columns(coefs)
        print(f"α = {alpha:>6} : 非ゼロ {len(coefs) - len(zeros)} 個 / ゼロになった列 {zeros} / R2 {r2:.4f}")

    # α を上げきると全部ゼロ = 「いつでも訓練データの平均を返すモデル」になる
    strongest = Lasso(alpha=1.0).fit(X_train_s, y_train)
    is_mean_model = bool(np.allclose(strongest.predict(X_test_s), y_train.mean()))
    print(f"\nα = 1.0 の予測が訓練データの星の平均と一致するか : {is_mean_model}")

    # 図：α を横軸（対数目盛）にして、4 つの係数がどう縮んでいくかを描く
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
    for ax, maker, title in [
        (axes[0], lambda a: Ridge(alpha=a), "Ridge（ゼロにはならない）"),
        (axes[1], lambda a: Lasso(alpha=a), "Lasso（順にゼロになる）"),
    ]:
        paths = {name: [] for name in X_train_s.columns}
        for alpha in FINE_ALPHAS:
            coefs, _ = fit_penalized(maker(alpha), X_train_s, y_train, X_test_s, y_test)
            for name in paths:
                paths[name].append(float(coefs[name]))
        for name, values in paths.items():
            ax.plot(FINE_ALPHAS, values, marker=".", label=LABEL_JA[name])
        ax.set_xscale("log")
        ax.axhline(0, color="#333333", linewidth=0.8)
        ax.set_title(title)
        ax.set_xlabel("α（正則化の強さ）")
    axes[0].set_ylabel("標準化後の係数")
    axes[1].legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "s16_alpha_path.png", dpi=110)
    plt.close(fig)
    print("\n図を保存しました: outputs/s16_alpha_path.png")


if __name__ == "__main__":
    main()
