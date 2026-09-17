"""pivot_table で 2 軸のクロス集計を作る。欠損したキーが消えることも確かめる。

    docker compose exec lab python src/session06/pivot_region_channel.py
"""

from __future__ import annotations

from common import load_tables, valid_orders


def main() -> None:
    _books, customers, orders = load_tables()
    valid = valid_orders(orders)

    df = valid.merge(
        customers[["customer_id", "region", "channel"]], on="customer_id", how="left"
    )
    print("■ 顧客の属性を結合する（行数が変わらないことを必ず確認）")
    print(f"有効注文: {len(valid):,} 件 → 結合後: {len(df):,} 行")

    pivot = df.pivot_table(
        index="region", columns="channel", values="revenue", aggfunc="sum"
    )
    print("\n■ region × channel の売上（円）")
    print(f"表の形        : {pivot.shape}")
    print(f"行（地域）    : {pivot.index.tolist()}")
    print(f"列（流入経路）: {pivot.columns.tolist()}")

    top_region, top_channel = pivot.stack().idxmax()
    top_value = round(float(pivot.loc[top_region, top_channel]))
    print(f"最大のセル    : {top_region} × {top_channel} = {top_value:,} 円")

    total = float(df["revenue"].sum())
    in_table = float(pivot.to_numpy().sum())
    missing = float(df.loc[df["region"].isna(), "revenue"].sum())
    print("\n■ 表に載らなかった売上")
    print(f"region が未入力の分: {round(missing):,} 円  ← 表のどこにも現れない")
    print(f"総額               : {round(total):,} 円")
    print(f"表の全セル + 未入力分が総額に戻るか: {abs(in_table + missing - total) < 0.01}")


if __name__ == "__main__":
    main()
