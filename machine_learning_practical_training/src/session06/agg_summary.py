"""agg で複数の集約をまとめ、列名を整える。

    docker compose exec lab python src/session06/agg_summary.py
"""

from __future__ import annotations

from common import load_tables, valid_orders


def main() -> None:
    books, _customers, orders = load_tables()
    valid = valid_orders(orders)
    df = valid.merge(books[["book_id", "category", "price"]], on="book_id", how="left")

    # 名前付き集約：出力の列名を自分で決める
    summary = df.groupby("category").agg(
        orders=("order_id", "count"),
        revenue=("revenue", "sum"),
        mean_quantity=("quantity", "mean"),
    )

    print("■ カテゴリ別の内訳（売上の多い順・表示するときだけ整数に丸める）")
    breakdown_sum = 0
    for row in summary.sort_values("revenue", ascending=False).itertuples():
        yen = round(float(row.revenue))
        breakdown_sum += yen
        print(
            f"{row.Index}: 注文 {int(row.orders):,} 件 / "
            f"売上 {yen:,} 円 / 平均数量 {float(row.mean_quantity):.3f} 冊"
        )

    print("\n■ 検算（集約したら必ず元の数に戻るか確かめる）")
    print(f"内訳の注文数の合計  : {int(summary['orders'].sum()):,} 件（有効注文と同じ）")
    print(f"丸めた内訳を足した額: {breakdown_sum:,} 円")
    print(f"本書の売上（総額）  : {round(float(df['revenue'].sum())):,} 円  ← 1 円ずれる")

    print("\n■ 平均価格は books マスタで数える（注文数の重みが入らない）")
    mean_price = books.groupby("category")["price"].mean().round()
    parts = [f"{c}: {int(v):,} 円" for c, v in mean_price.sort_values(ascending=False).items()]
    print(" / ".join(parts))


if __name__ == "__main__":
    main()
