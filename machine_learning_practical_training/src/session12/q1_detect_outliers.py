"""問題1 の解答: 外れ値を検出する関数を書き、IQR 法と 3σ 法を比べる。

使い方:
    docker compose exec lab python src/session12/q1_detect_outliers.py
"""

from __future__ import annotations

import pandas as pd

from common import BULK_THRESHOLD, load_orders


def my_outlier_bounds(values: pd.Series, method: str) -> tuple[float, float]:
    """外れ値の下限・上限を返す。method は "iqr" か "sigma"。"""
    if method == "iqr":
        q1, q3 = values.quantile(0.25), values.quantile(0.75)
        iqr = q3 - q1
        return float(q1 - 1.5 * iqr), float(q3 + 1.5 * iqr)
    if method == "sigma":
        mean, sd = values.mean(), values.std()
        return float(mean - 3 * sd), float(mean + 3 * sd)
    # 想定外の文字列を黙って無視すると、外れ値 0 件という誤った結論になる
    raise ValueError(f"method は 'iqr' か 'sigma' です: {method!r}")


def summarize(values: pd.Series, method: str) -> pd.Series:
    lower, upper = my_outlier_bounds(values, method)
    mask = (values < lower) | (values > upper)
    print(f"{method:6} : 上限 {upper:.4f} / 外れ値 {int(mask.sum()):,} 件（{mask.mean():.1%}）"
          f" / 下限を下回る行 {int((values < lower).sum()):,} 件")
    return mask


def main() -> None:
    quantity = load_orders()["quantity"]
    q1, q3 = quantity.quantile(0.25), quantity.quantile(0.75)

    print(f"■ quantity（{len(quantity):,} 行）")
    print(f"平均 {quantity.mean():.4f} / 中央値 {quantity.median():.1f} "
          f"/ 最頻値 {int(quantity.mode().iloc[0])} / 標準偏差 {quantity.std():.4f}")
    print(f"Q1 {q1:.1f} / Q3 {q3:.1f} / IQR {q3 - q1:.1f}")
    print(f"4〜14 冊の注文 : {int(quantity.between(4, 14).sum()):,} 件")
    print(f"{BULK_THRESHOLD} 冊以上の注文 : {int((quantity >= BULK_THRESHOLD).sum()):,} 件"
          f"（最大 {int(quantity.max())} 冊）")
    print()

    iqr_mask = summarize(quantity, "iqr")
    sigma_mask = summarize(quantity, "sigma")
    print()
    print(f"3σ 法の結果が「{BULK_THRESHOLD} 冊以上」と一致するか : "
          f"{bool(sigma_mask.equals(quantity >= BULK_THRESHOLD))}")
    print(f"IQR 法だけが外れ値とした件数 : {int((iqr_mask & ~sigma_mask).sum()):,} 件")
    print()
    print("結論: IQR 法は「真ん中 50% に幅がある」ことを前提にしている。")
    print("      quantity は Q1 = Q3 = 1 で IQR = 0 なので、この前提が崩れて使えない。")

    try:
        my_outlier_bounds(quantity, "3sigma")
    except ValueError as error:
        print(f"想定外の method は例外にする : {type(error).__name__}")


if __name__ == "__main__":
    main()
