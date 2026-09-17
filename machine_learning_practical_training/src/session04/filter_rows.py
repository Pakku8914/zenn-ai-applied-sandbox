"""条件で行を絞る：ブールインデックスと query。

使い方:
    docker compose exec lab python src/session04/filter_rows.py
"""

from __future__ import annotations

from common import load_orders


def main() -> None:
    orders = load_orders()

    mask = orders["quantity"] >= 15  # 全行分の True / False が並んだ Series
    print("■ ブールインデックス")
    print(f"mask の型と dtype: {type(mask).__name__} / {mask.dtype}")
    print(f"条件に合う件数   : {mask.sum()} 件")
    print(f"quantity の最大値: {orders['quantity'].max()}")
    print(f"抽出結果の形     : {orders.loc[mask].shape}")

    print("\n■ 複数条件（& と | は括弧で囲む）")
    both = orders.loc[(orders["quantity"] >= 15) & (orders["discount_rate"] == 0.2)]
    print(f"15 冊以上かつ 20% 引き: {len(both)} 件")

    print("\n■ query なら条件を文章のように書ける")
    threshold = 15
    queried = orders.query("quantity >= @threshold and discount_rate == 0.2")
    print(f"query の結果        : {len(queried)} 件")
    print(f"& の結果と一致するか: {both.equals(queried)}")

    print("\n■ そのほかよく使う書き方")
    print(f"isin（顧客を指定）        : {orders['customer_id'].isin(['C00001']).sum()} 件")
    print(f"between（15 以上 39 以下）: {orders['quantity'].between(15, 39).sum()} 件")
    print(f"~ で否定した件数との合計が全行数か: {(~mask).sum() + mask.sum() == len(orders)}")


if __name__ == "__main__":
    main()
