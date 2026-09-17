"""merge の基本形 ― キーの一意性の確認、列の増え方、同名列の衝突。

使い方:
    docker compose exec lab python src/session05/merge_basics.py
"""

from __future__ import annotations

import pandas as pd

from common import load_all, report


def revenue(df: pd.DataFrame) -> float:
    """売上（本書の共通ルール：行ごとに丸めず、合計してから整数にする）。"""
    return float((df["unit_price"] * df["quantity"] * (1 - df["discount_rate"])).sum())


def main() -> None:
    books, customers, orders, reviews = load_all()
    orders_dedup = orders.drop_duplicates()

    print("■ 結合の前に確かめること（行数とキーの一意性）")
    print(f"  books             : {len(books):>6,} 行 / book_id     が一意な数 {books['book_id'].nunique():>6,}")
    print(f"  customers         : {len(customers):>6,} 行 / customer_id が一意な数 {customers['customer_id'].nunique():>6,}")
    print(f"  orders（生）      : {len(orders):>6,} 行 / order_id    が一意な数 {orders['order_id'].nunique():>6,}")
    print(f"  orders（重複排除）: {len(orders_dedup):>6,} 行 / order_id    が一意な数 {orders_dedup['order_id'].nunique():>6,}")
    print(f"  reviews           : {len(reviews):>6,} 行 / order_id    が一意な数 {reviews['order_id'].nunique():>6,}")

    print("\n■ 注文に書籍マスタをくっつける（多対一の結合）")
    enriched = orders_dedup.merge(books, on="book_id", how="inner")
    report("  orders_dedup + books", len(orders_dedup), len(enriched))
    print(f"  列数: {orders_dedup.shape[1]} 列 + {books.shape[1]} 列 - キーの 1 列 = {enriched.shape[1]} 列")
    print(f"  増えた列: {list(enriched.columns[-4:])}")
    print(f"  category の欠損: {enriched['category'].isna().sum()} 件")

    valid = orders_dedup.loc[orders_dedup["is_canceled"] == 0]
    valid_enriched = valid.merge(books, on="book_id", how="inner", validate="many_to_one")
    print(f"  売上の検算: {revenue(valid):,.0f} 円 → {revenue(valid_enriched):,.0f} 円")

    print("\n■ 同じ名前の列が左右にあるとどうなるか（suffixes）")
    with_orders = reviews.merge(orders_dedup, on="order_id", how="inner")
    report("  reviews + orders_dedup", len(reviews), len(with_orders))
    collided = [c for c in with_orders.columns if c.startswith(("customer_id", "book_id"))]
    print(f"  重なった列: {collided}")
    print(f"  列数: {with_orders.shape[1]} 列")

    needed = ["order_id", "ordered_at", "quantity", "unit_price", "discount_rate", "is_canceled"]
    slim = reviews.merge(orders_dedup[needed], on="order_id", how="inner", validate="one_to_one")
    print(f"  必要な列だけに絞ると: {len(slim):,} 行 {slim.shape[1]} 列（衝突なし）")


if __name__ == "__main__":
    main()
