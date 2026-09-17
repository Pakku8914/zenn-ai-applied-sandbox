"""列と行の選び方：loc（ラベル）と iloc（位置）の違いを確かめる。

使い方:
    docker compose exec lab python src/session04/loc_iloc.py
"""

from __future__ import annotations

from common import load_orders


def main() -> None:
    orders = load_orders()

    print("■ 列の選び方")
    print(f"1 列だけ選ぶ    : {type(orders['quantity']).__name__}")
    two_cols = orders[["order_id", "quantity"]]
    print(f"列のリストで選ぶ: {type(two_cols).__name__} / 形 {two_cols.shape}")

    print("\n■ iloc[0]（位置 0）と loc[0]（ラベル 0）")
    first = orders.iloc[0]
    print(f"iloc[0] の order_id : {first['order_id']}")
    print(f"iloc[0] の注文日    : {first['ordered_at'].date()}")
    print(f"iloc[0] の quantity : {first['quantity']}")
    print(f"loc[0] の order_id  : {orders.loc[0, 'order_id']}")

    print("\n■ スライスの終端の扱い")
    print(f"loc[0:2] : {len(orders.loc[0:2])} 行（終端を含む）")
    print(f"iloc[0:2]: {len(orders.iloc[0:2])} 行（終端を含まない）")

    print("\n■ インデックスを付け替えると loc の意味が変わる")
    picked = orders.set_index("customer_id").loc["C00001"]
    print(f"loc['C00001'] : {len(picked)} 行 / {type(picked).__name__}")


if __name__ == "__main__":
    main()
