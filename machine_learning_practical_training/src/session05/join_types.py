"""4 種類の how（inner / left / right / outer）と indicator の比較。

使い方:
    docker compose exec lab python src/session05/join_types.py
"""

from __future__ import annotations

from common import load_customers, load_orders, load_reviews


def main() -> None:
    customers = load_customers()
    orders = load_orders()
    reviews = load_reviews()
    orders_dedup = orders.drop_duplicates()

    print("■ 顧客に注文をくっつける ― how を変えて行数を比べる")
    print(f"  左: customers {len(customers):,} 行 / 右: orders_dedup {len(orders_dedup):,} 行")
    print("  how     行数    顧客数  order_id が NaN の行")
    for how in ("inner", "left", "right", "outer"):
        joined = customers.merge(orders_dedup, on="customer_id", how=how)
        print(
            f"  {how:<6}{len(joined):>7,}{joined['customer_id'].nunique():>8,}"
            f"{int(joined['order_id'].isna().sum()):>10,}"
        )

    buyers = orders_dedup["customer_id"].nunique()
    no_orders = len(customers) - buyers
    left_join = customers.merge(orders_dedup, on="customer_id", how="left")
    print(f"  注文が 1 件もない顧客: {len(customers):,} - {buyers:,} = {no_orders:,} 人")
    print(
        f"  left 結合の行数の検算: {len(orders_dedup):,} + {no_orders:,} = {len(left_join):,}"
        f" → {len(orders_dedup) + no_orders == len(left_join)}"
    )

    print("\n■ NaN が混ざると数値列の型が変わる")
    print(f"  結合前の quantity の型: {orders_dedup['quantity'].dtype}")
    print(f"  left 結合後の型        : {left_join['quantity'].dtype}")
    print(f"  left 結合後の order_id の欠損: {int(left_join['order_id'].isna().sum()):,} 件")

    print("\n■ どちら側にしかないキーを数える（indicator=True）")
    flagged = orders_dedup.merge(
        reviews[["order_id", "rating"]], on="order_id", how="left", indicator=True
    )
    print(f"  both      : {int((flagged['_merge'] == 'both').sum()):>6,}")
    print(f"  left_only : {int((flagged['_merge'] == 'left_only').sum()):>6,}")
    print(f"  right_only: {int((flagged['_merge'] == 'right_only').sum()):>6,}")
    print(f"  合計      : {len(flagged):,} 行（orders_dedup と同じ = {len(flagged) == len(orders_dedup)}）")


if __name__ == "__main__":
    main()
