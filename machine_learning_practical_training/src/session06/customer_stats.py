"""顧客単位に集約する（顧客数の数え方は 3 通りある）。

    docker compose exec lab python src/session06/customer_stats.py
"""

from __future__ import annotations

from common import load_tables, valid_orders


def main() -> None:
    _books, customers, orders = load_tables()
    ordered = orders.drop_duplicates()["customer_id"].nunique()
    valid = valid_orders(orders)
    revenue = valid.groupby("customer_id")["revenue"].sum()

    print(f"① customers.csv の行数        : {len(customers):,} 人")
    print(f"② 注文が 1 件以上ある顧客     : {ordered:,} 人")
    print(f"③ 有効注文が 1 件以上ある顧客 : {len(revenue):,} 人  ← 売上の分母")
    print(f"顧客あたり売上の平均          : {float(revenue.mean()):,.1f} 円")
    print(f"顧客あたり売上の中央値        : {float(revenue.median()):,.1f} 円")


if __name__ == "__main__":
    main()
