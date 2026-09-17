"""実装問題 7：集計の検算 ― 行数・丸め方・欠けたキーを自分の手で確かめる。

使い方:
    docker compose exec lab python src/review01/q7_reconcile.py
"""

from __future__ import annotations

from pandas.errors import MergeError

from common import (
    load_books,
    load_customers,
    load_orders,
    load_reviews,
    load_valid_orders,
    show_rows,
    yen,
)


def step1_population() -> None:
    """母集団を 3 段で決める（セッション 2・4・6）。"""
    raw = load_orders(dedupe=False)
    orders = load_orders()
    valid = orders.loc[orders["is_canceled"] == 0]
    canceled = orders.loc[orders["is_canceled"] == 1]

    print("■ 1. 母集団を 3 段で決める")
    print(f"  完全重複した行: {int(raw.duplicated().sum())} 件")
    show_rows("  生の注文 → 重複排除", len(raw), len(orders))
    show_rows("  重複排除 → 有効注文", len(orders), len(valid))
    print(f"  キャンセル: {len(canceled):,} 件（{len(canceled) / len(orders):.2%}）")
    total = len(valid) + len(canceled)
    print(f"  検算: {len(valid):,} + {len(canceled):,} = {total:,} → {total == len(orders)}")


def step2_merge() -> None:
    """結合の前後で行数を検算する（セッション 4・5）。"""
    reviews = load_reviews()
    raw = load_orders(dedupe=False)
    orders = load_orders()
    customers = load_customers()

    print("■ 2. 結合の前後で行数を検算する")
    naive = reviews.merge(raw, on="order_id", how="inner")
    show_rows("  レビュー × 生の注文", len(reviews), len(naive))
    print(f"  二重に現れた review_id: {int(naive['review_id'].duplicated().sum())} 件")
    safe = reviews.merge(orders, on="order_id", how="inner", validate="one_to_one")
    show_rows("  レビュー × 重複排除後の注文", len(reviews), len(safe))
    try:
        reviews.merge(raw, on="order_id", how="inner", validate="many_to_one")
        print("  validate='many_to_one': 例外は出なかった（重複が残っていない？）")
    except MergeError as exc:
        print(f"  validate='many_to_one': {type(exc).__name__}: {str(exc).splitlines()[0]}")

    buyers = orders["customer_id"].nunique()
    no_orders = len(customers) - buyers
    left = customers.merge(orders, on="customer_id", how="left")
    show_rows("  顧客 × 注文（how='left'）", len(customers), len(left))
    expected = len(orders) + no_orders
    print(f"  検算: {len(orders):,} + 注文のない顧客 {no_orders} 人 = {expected:,} → {expected == len(left)}")

    flagged = orders.merge(
        reviews[["order_id", "rating"]], on="order_id", how="left", indicator=True
    )
    for side in ("both", "left_only", "right_only"):
        print(f"  indicator {side}: {int((flagged['_merge'] == side).sum()):,} 行")


def step3_rounding() -> None:
    """売上は最後に一度だけ丸める（セッション 6）。"""
    valid = load_valid_orders()
    books = load_books()
    total = float(valid["revenue"].sum())
    row_rounded = int(valid["revenue"].round().sum())

    print("■ 3. 丸める順番で答えが変わる")
    print(f"  合計してから丸める : {yen(total)}")
    print(f"  行ごとに丸めて合計 : {row_rounded:,} 円（{row_rounded - round(total):+,} 円）")
    by_category = (
        valid.merge(books[["book_id", "category"]], on="book_id", how="left", validate="many_to_one")
        .groupby("category")["revenue"]
        .sum()
        .sort_values(ascending=False)
    )
    for category, revenue in by_category.items():
        print(f"    {category}: {yen(revenue)}")
    breakdown = sum(round(float(v)) for v in by_category)
    print(f"  丸めた内訳の合計   : {breakdown:,} 円（{breakdown - round(total):+,} 円）")


def step4_missing_key() -> None:
    """キーが欠けた行は集計から黙って落ちる（セッション 6）。"""
    valid = load_valid_orders()
    customers = load_customers()
    joined = valid.merge(
        customers[["customer_id", "region", "channel"]],
        on="customer_id",
        how="left",
        validate="many_to_one",
    )
    total = float(joined["revenue"].sum())
    pivot = joined.pivot_table(index="region", columns="channel", values="revenue", aggfunc="sum")
    in_table = float(pivot.to_numpy().sum())
    dropped = float(joined.loc[joined["region"].isna(), "revenue"].sum())
    region, channel = pivot.stack().idxmax()

    print("■ 4. キーが欠けた行は集計から黙って落ちる")
    print(f"  pivot_table の形: {pivot.shape[0]} 行 × {pivot.shape[1]} 列（空のセル {int(pivot.isna().sum().sum())} 個）")
    print(f"  最大のセル: {region} × {channel} = {yen(pivot.loc[region, channel])}")
    print(f"  region 未入力の売上 : {yen(dropped)}")
    print(f"  検算: 表の全セル + 未入力 = 総額 → {abs(in_table + dropped - total) < 0.01}")
    ratio = customers["region"].isna().mean()
    print(f"  region の欠損: {int(customers['region'].isna().sum())} 件（{ratio:.2%}）")


def step5_customers() -> None:
    """顧客数は 3 通り。どれを使ったかを書く（セッション 6）。"""
    customers = load_customers()
    orders = load_orders()
    valid = load_valid_orders()
    buyers = orders["customer_id"].nunique()

    print("■ 5. 顧客数は 3 通りある")
    print(f"  ① 全顧客             : {len(customers):,} 人")
    print(f"  ② 注文のある顧客     : {buyers:,} 人")
    print(f"  ③ 有効注文のある顧客 : {valid['customer_id'].nunique():,} 人")
    print(f"  注文が 1 件もない顧客: {len(customers) - buyers} 人")


def main() -> None:
    step1_population()
    step2_merge()
    step3_rounding()
    step4_missing_key()
    step5_customers()


if __name__ == "__main__":
    main()
