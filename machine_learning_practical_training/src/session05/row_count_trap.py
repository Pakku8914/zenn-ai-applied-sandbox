"""結合キーの重複で行がこっそり増える現象を再現し、防ぎ方を確かめる。

使い方:
    docker compose exec lab python src/session05/row_count_trap.py
"""

from __future__ import annotations

import pandas as pd
from pandas.errors import MergeError

from common import load_orders, load_reviews, report


def main() -> None:
    orders = load_orders()
    reviews = load_reviews()
    orders_dedup = orders.drop_duplicates()

    print("■ 重複を落とさずに結合すると何が起きるか")
    naive = reviews.merge(orders, on="order_id", how="inner")
    safe = reviews.merge(orders_dedup, on="order_id", how="inner")
    report("  reviews + orders（生）      ", len(reviews), len(naive))
    report("  reviews + orders（重複排除）", len(reviews), len(safe))
    print(f"  二重に現れた review_id: {int(naive['review_id'].duplicated().sum())} 件")

    dup_ids = orders.loc[orders.duplicated(subset="order_id"), "order_id"]
    print(
        f"  内訳: orders 側で重複していた注文 {len(dup_ids)} 件のうち、"
        f"レビューがあったのは {int(reviews['order_id'].isin(dup_ids).sum())} 件"
    )

    print("\n■ 小さな表で直積を再現する")
    left_toy = pd.DataFrame({"key": ["A", "A", "B"], "left_val": [1, 2, 3]})
    right_toy = pd.DataFrame({"key": ["A", "A", "C"], "right_val": [10, 20, 30]})
    print(f"  left  の key: {left_toy['key'].tolist()}")
    print(f"  right の key: {right_toy['key'].tolist()}")
    print(f"  how=\"inner\": {len(left_toy.merge(right_toy, on='key', how='inner'))} 行（A が 2 × 2 になる）")
    print(f"  how=\"outer\": {len(left_toy.merge(right_toy, on='key', how='outer'))} 行")
    print(f"  how=\"cross\": {len(left_toy.merge(right_toy, how='cross'))} 行（キーを見ない全組み合わせ）")

    print("\n■ validate で pandas に見張らせる")
    try:
        reviews.merge(orders, on="order_id", how="inner", validate="many_to_one")
        print("  例外は出ませんでした（想定外）")
    except MergeError as exc:
        # 例外文には重複キーの一覧が続くので、1 行目だけを表示する
        print(f"  MergeError: {str(exc).splitlines()[0]}")
    checked = reviews.merge(orders_dedup, on="order_id", how="inner", validate="one_to_one")
    print(f"  重複排除後に validate=\"one_to_one\" → OK（{len(checked):,} 行）")

    print("\n■ キーの型が違うと ValueError になる")
    str_key = pd.DataFrame({"book_id": ["B0001", "B0002"], "memo": ["a", "b"]})
    int_key = pd.DataFrame({"book_id": [1, 2], "price": [3200, 1800]})
    try:
        str_key.merge(int_key, on="book_id", how="inner")
        print("  例外は出ませんでした（想定外）")
    except ValueError as exc:
        print(f"  {type(exc).__name__}: {str(exc).split('. ')[0]}.")

    print("\n■ 書式が違うキーは、エラーも出ずに 0 件になる")
    zero_padded = pd.DataFrame({"book_id": ["1", "2"], "price": [3200, 1800]})
    print(f"  \"B0001\" と \"1\" を結合した行数: {len(str_key.merge(zero_padded, on='book_id', how='inner'))} 行")


if __name__ == "__main__":
    main()
