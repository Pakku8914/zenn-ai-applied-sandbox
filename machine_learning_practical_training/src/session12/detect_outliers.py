"""外れ値を IQR 法と 3σ 法の 2 通りで検出し、結果の違いを数える。

使い方:
    docker compose exec lab python src/session12/detect_outliers.py
"""

from __future__ import annotations

import pandas as pd

from common import BULK_THRESHOLD, load_orders, outlier_bounds, outlier_mask


def report(values: pd.Series, method: str, label: str) -> pd.Series:
    """外れ値の上限と件数を表示し、外れ値のマスクを返す。"""
    lower, upper = outlier_bounds(values, method)
    mask = outlier_mask(values, method)
    print(f"{label}: 上限 {upper:.4f} を上回る行 {int((values > upper).sum()):,} 件"
          f"（全体の {mask.mean():.1%}）")
    print(f"        下限を下回る行 {int((values < lower).sum()):,} 件")
    return mask


def main() -> None:
    orders = load_orders()
    quantity = orders["quantity"]

    print(f"■ quantity の分布（重複を除いた {len(orders):,} 行）")
    print(f"平均 {quantity.mean():.4f} / 中央値 {quantity.median():.1f} "
          f"/ 最頻値 {int(quantity.mode().iloc[0])} / 標準偏差 {quantity.std():.4f}")
    print(f"1〜3 冊   : {int(quantity.between(1, 3).sum()):,} 件")
    print(f"4〜14 冊  : {int(quantity.between(4, 14).sum()):,} 件")
    print(f"15 冊以上 : {int((quantity >= BULK_THRESHOLD).sum()):,} 件（最大 {int(quantity.max())} 冊）")
    print()

    q1, q3 = quantity.quantile(0.25), quantity.quantile(0.75)
    print("■ 外れ値の線を 2 通りの方法で引く")
    print(f"IQR 法 の材料 : Q1 {q1:.1f} / Q3 {q3:.1f} / IQR {q3 - q1:.1f}")
    iqr_mask = report(quantity, "iqr", "IQR 法 ")
    print(f"3σ 法 の材料  : 平均 {quantity.mean():.4f} / 標準偏差 {quantity.std():.4f}")
    sigma_mask = report(quantity, "sigma", "3σ 法  ")
    print()

    bulk_mask = quantity >= BULK_THRESHOLD
    print("■ 2 つの結果を突き合わせる")
    print(f"3σ 法の結果が「{BULK_THRESHOLD} 冊以上」と完全に一致するか : {bool(sigma_mask.equals(bulk_mask))}")
    print(f"IQR 法だけが外れ値とした件数 : {int((iqr_mask & ~sigma_mask).sum()):,} 件")
    kinds = [int(v) for v in sorted(quantity.loc[iqr_mask & ~sigma_mask].unique())]
    print(f"その中身（冊数の種類）       : {kinds} 冊")

    # 手法が使えるかどうかを、使う前に自分で確かめる
    if q3 - q1 == 0:
        print()
        print("⚠ IQR が 0 です。この列に IQR 法を当てると、真ん中 50% から外れた値がすべて")
        print("  外れ値になります。分布が特定の値に固まっている列では別の方法を使ってください。")


if __name__ == "__main__":
    main()
