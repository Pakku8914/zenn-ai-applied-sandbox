"""transform で集約結果を元の行数のまま戻す。

    docker compose exec lab python src/session06/transform_diff.py
"""

from __future__ import annotations

import pandas as pd

from common import load_tables, valid_orders


def main() -> None:
    print("■ 集約と transform の違い（3 行の小さな表）")
    toy = pd.DataFrame({"customer": ["A", "A", "B"], "amount": [100, 300, 500]})
    grouped = toy.groupby("customer")["amount"].sum()
    spread = toy.groupby("customer")["amount"].transform("sum")
    print(f"sum       : {grouped.to_dict()}（{len(grouped)} 行）")
    print(f"transform : {spread.tolist()}（{len(spread)} 行）")

    _books, _customers, orders = load_tables()
    df = valid_orders(orders)
    before = len(df)

    df["customer_mean"] = df.groupby("customer_id")["revenue"].transform("mean")
    df["diff_from_mean"] = df["revenue"] - df["customer_mean"]

    print("\n■ 実データに戻す（行数が変わらない）")
    print(f"列を足す前の行数    : {before:,} 行")
    print(f"列を足した後の行数  : {len(df):,} 行")
    print(f"顧客数（比較用）    : {df['customer_id'].nunique():,} 人")
    print(f"差の合計（0 になる）: {abs(float(df['diff_from_mean'].sum())):.0f} 円")


if __name__ == "__main__":
    main()
