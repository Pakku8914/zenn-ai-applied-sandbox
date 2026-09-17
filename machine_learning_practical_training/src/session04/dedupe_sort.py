"""重複行の検出・除去と、複数キーの並べ替え。

使い方:
    docker compose exec lab python src/session04/dedupe_sort.py
"""

from __future__ import annotations

import pandas as pd

from common import load_orders


def main() -> None:
    orders = load_orders()

    print("■ 重複行")
    print(f"読み込んだ行数          : {len(orders)} 行")
    print(f"完全に重複している行    : {orders.duplicated().sum()} 件")
    print(f"order_id で見た重複     : {orders.duplicated(subset='order_id').sum()} 件")
    unique_orders = orders.drop_duplicates()  # 返り値を必ず受け取る
    print(f"drop_duplicates() 後    : {len(unique_orders)} 行")
    valid = unique_orders.loc[unique_orders["is_canceled"] == 0]
    print(f"さらにキャンセルを除くと: {len(valid)} 件")

    print("\n■ keep の違い（3 行の小さな表で確かめる）")
    toy = pd.DataFrame({"order_id": ["O1", "O1", "O2"], "quantity": [1, 1, 2]})
    print(f"duplicated()           : {toy.duplicated().tolist()}")
    print(f"duplicated(keep='last'): {toy.duplicated(keep='last').tolist()}")
    print(f"duplicated(keep=False) : {toy.duplicated(keep=False).tolist()}")

    print("\n■ 並べ替え")
    recent = orders.sort_values(["customer_id", "ordered_at"], ascending=[True, False])
    by_qty = orders.sort_values("quantity", ascending=False)
    print(f"quantity 降順の先頭    : {by_qty.iloc[0]['quantity']}")
    print(f"customer_id 昇順の先頭 : {recent.iloc[0]['customer_id']}")
    print(f"reset_index 後の先頭   : {recent.reset_index(drop=True).index[0]}")
    print(f"元の orders の先頭     : {orders.iloc[0]['order_id']}")


if __name__ == "__main__":
    main()
