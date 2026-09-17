"""問題4: VIF を自分で計算し、写しの列を足したときの係数の暴れを再現する。

使い方:
    docker compose exec lab python src/session16/q4_vif_check.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from common import (
    CORE_FEATURES,
    FEATURES,
    TARGET,
    add_pages_dup,
    fit_ols,
    load_rated_reviews,
    vif_table,
)

DUP_FEATURES = CORE_FEATURES + ["pages_dup"]


def vif_by_hand(X: pd.DataFrame, column: str) -> float:
    """VIF の定義そのままの計算。ある列を「残りの列」で説明したときの 1 / (1 - R2)。"""
    others = [name for name in X.columns if name != column]
    r_squared = fit_ols(X[others], X[column]).rsquared  # 切片は fit_ols の中で足している
    return float(1.0 / (1.0 - r_squared))


def vif_all_by_hand(X: pd.DataFrame) -> pd.Series:
    """すべての列について自作の VIF を計算する。"""
    return pd.Series({name: vif_by_hand(X, name) for name in X.columns})


def show_vif(vif: pd.Series) -> None:
    """列の順番どおりに表示する（並べ替えると同じ値の列の順序が読めなくなる）。"""
    for name, value in vif.items():
        print(f"{name:<15}: {value:,.0f}" if value >= 1000 else f"{name:<15}: {value:.3f}")


def main() -> None:
    df = load_rated_reviews()
    y = df[TARGET]

    mine, theirs = vif_all_by_hand(df[FEATURES]), vif_table(df[FEATURES])
    print("■ 自作の VIF と statsmodels の VIF")
    print(f"すべての列で一致するか : {bool(np.allclose(mine[FEATURES].to_numpy(), theirs[FEATURES].to_numpy()))}")
    show_vif(theirs)
    print(f"VIF が 10 を超えた列 : {[str(name) for name, value in theirs.items() if value > 10]}")

    print("\n■ pages の写しを 1 本足す（pages_dup = pages * 6 + ノイズ）")
    dup = add_pages_dup(df)
    show_vif(vif_table(dup[DUP_FEATURES]))

    before = fit_ols(df[CORE_FEATURES], y)
    after = fit_ols(dup[DUP_FEATURES], y)
    print("\n■ pages の係数と p 値（14,169 件・statsmodels）")
    print(f"写しなし : {before.params['pages']:+.5f} / p 値 {before.pvalues['pages']:.2e}")
    print(f"写しあり : {after.params['pages']:+.5f} / p 値 {after.pvalues['pages']:.4f}")
    print(f"符号が反転したか : {bool(before.params['pages'] * after.params['pages'] < 0)}")
    print(f"写しありで p < 0.05 か : {bool(after.pvalues['pages'] < 0.05)}")
    print(f"当てはまり（R2）の差が 0.001 未満か : {bool(abs(before.rsquared - after.rsquared) < 0.001)}")

    print("\n■ 判断")
    print("VIF が跳ねてもモデルの当てはまりは落ちません。壊れたのは予測ではなく「係数の解釈」です。")
    print("pages と pages_dup は同じ情報を持つので、どちらにどれだけ配分しても予測はほぼ同じになり、")
    print("配分の決め方がノイズに左右されます。だから係数が符号ごと動き、p 値も大きくなります。")


if __name__ == "__main__":
    main()
