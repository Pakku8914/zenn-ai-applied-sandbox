"""多重共線性 ― 同じ情報が二重に入っていると係数が暴れることを再現する。

この節だけは訓練データに分けず 14,169 件すべてを使います。多重共線性は
「データそのものの性質」なので、分割してもしなくても同じ話になるためです。

使い方:
    docker compose exec lab python src/session16/multicollinearity.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    CORE_FEATURES,
    FEATURES,
    LABEL_JA,
    OUT_DIR,
    RANDOM_STATE,
    TARGET,
    add_pages_dup,
    fit_ols,
    load_rated_reviews,
    vif_table,
)

DUP_FEATURES = CORE_FEATURES + ["pages_dup"]  # published_year を外し、代わりに写しを足した 4 列


def show_vif(vif) -> None:
    """VIF を列の順番どおりに表示する（桁が大きく違うので書式だけ分ける）。"""
    for name, value in vif.items():
        print(f"{name:<15}: {value:,.0f}" if value >= 1000 else f"{name:<15}: {value:.3f}")
    print(f"VIF が 10 を超えた列 : {[str(name) for name, value in vif.items() if value > 10]}")


def main() -> None:
    df = load_rated_reviews()
    y = df[TARGET]

    print("■ 4 つの特徴量の VIF（14,169 件・切片の列を足して計算）")
    show_vif(vif_table(df[FEATURES]))
    print(f"corr(pages, price) = {df['pages'].corr(df['price']):+.4f}")

    print(f"\n■ ページ数とほとんど同じ情報しか持たない列を 1 本足す（シード {RANDOM_STATE}）")
    print("pages_dup = pages * 6 + ノイズ（平均 0・標準偏差 1）")
    dup = add_pages_dup(df)
    print(f"corr(pages, pages_dup) = {dup['pages'].corr(dup['pages_dup']):+.6f}")
    show_vif(vif_table(dup[DUP_FEATURES]))

    base = fit_ols(df[FEATURES], y)  # 写しなし・4 列
    core = fit_ols(df[CORE_FEATURES], y)  # 写しなし・published_year を外した 3 列
    shaken = fit_ols(dup[DUP_FEATURES], y)  # 写しあり

    print("\n■ pages の係数はどう動いたか（14,169 件・statsmodels）")
    print(f"写しなし（4 列）        : {base.params['pages']:+.5f} / p 値 {base.pvalues['pages']:.2e}")
    print(f"写しなし（3 列）        : {core.params['pages']:+.5f} / p 値 {core.pvalues['pages']:.2e}")
    print(f"写しあり（+ pages_dup） : {shaken.params['pages']:+.5f} / p 値 {shaken.pvalues['pages']:.4f}")
    print(f"写しありでも p < 0.05 か : {bool(shaken.pvalues['pages'] < 0.05)}")

    print("\n■ 写しありのモデルのほかの係数（ここはほとんど動いていない）")
    for name in ["price", "body_length"]:
        print(f"{name:<15}: {shaken.params[name]:+.5f}")
    print(f"{'切片':<13}: {shaken.params['const']:+.5f}")
    print(f"当てはまり（R2）の差が 0.001 未満か : {bool(abs(core.rsquared - shaken.rsquared) < 0.001)}")

    # 図：VIF の桁と、係数が符号ごと動いたことを並べて見せる
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    vif_after = vif_table(dup[DUP_FEATURES])
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    axes[0].bar(
        [LABEL_JA[name] for name in vif_after.index],
        vif_after.to_numpy(),
        color=["#4c78a8" if value <= 10 else "#d62728" for value in vif_after],
    )
    axes[0].set_yscale("log")
    axes[0].axhline(10, color="#333333", linestyle="--", linewidth=0.8, label="目安の 10")
    axes[0].set_title("写しを足したあとの VIF（対数目盛）")
    axes[0].set_ylabel("VIF")
    axes[0].legend(loc="upper left", fontsize=8)
    axes[1].bar(
        ["写しなし（3 列）", "写しあり（4 列）"],
        [float(core.params["pages"]), float(shaken.params["pages"])],
        color=["#4c78a8", "#d62728"],
    )
    axes[1].axhline(0, color="#333333", linewidth=0.8)
    axes[1].set_title("ページ数の係数が符号ごと動く")
    axes[1].set_ylabel("pages の係数")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "s16_vif_shock.png", dpi=110)
    plt.close(fig)
    print("\n図を保存しました: outputs/s16_vif_shock.png")


if __name__ == "__main__":
    main()
