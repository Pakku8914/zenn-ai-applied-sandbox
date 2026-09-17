"""groupby の「分割 → 適用 → 結合」を確かめる。

    docker compose exec lab python src/session06/groupby_basics.py
"""

from __future__ import annotations

from common import load_tables, valid_orders


def main() -> None:
    books, _customers, orders = load_tables()
    valid = valid_orders(orders)
    df = valid.merge(books[["book_id", "category", "price"]], on="book_id", how="left")

    print("■ 母集団をそろえてから集計する")
    print(f"有効注文        : {len(valid):,} 件")
    print(f"books を結合後  : {len(df):,} 行（結合前と同じ）")
    print(f"category の種類 : {df['category'].nunique()} 種類")

    counts = df.groupby("category").size()

    print("\n■ カテゴリ別の注文数（多い順）")
    for category, count in counts.sort_values(ascending=False).items():
        print(f"{category}: {int(count):,} 件")
    print(f"合計: {int(counts.sum()):,} 件")

    print("\n■ 既定ではキーの順（日本語は文字コード順）に並ぶ")
    print(f"{counts.index.tolist()}")
    counted = df.groupby("category")["order_id"].count()
    print(f"size と count が一致: {counted.tolist() == counts.tolist()}")


if __name__ == "__main__":
    main()
