"""セッション 5 の検証スクリプト。

「セッション5：テーブルを結合する ― merge と concat」の本文・練習問題・解答に
載せた数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session05/verify_05.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from pandas.errors import MergeError

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    ok = actual == expected
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual}")
    if not ok:
        print(f"     期待値: {expected}")
        failures.append(label)


missing = [
    name for name in ("books", "customers", "orders", "reviews")
    if not (DATA_DIR / f"{name}.csv").exists()
]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

books = pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"})
customers = pd.read_csv(
    DATA_DIR / "customers.csv", dtype={"customer_id": "str"}, parse_dates=["signup_date"]
)
orders = pd.read_csv(
    DATA_DIR / "orders.csv",
    dtype={"order_id": "str", "customer_id": "str", "book_id": "str"},
    parse_dates=["ordered_at"],
)
reviews = pd.read_csv(
    DATA_DIR / "reviews.csv",
    dtype={"review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str"},
    parse_dates=["reviewed_at"],
)
orders_dedup = orders.drop_duplicates()

# 1. 結合の前提（行数・列数・キーの一意性）
check("books.csv の行数", len(books), 600)
check("customers.csv の行数", len(customers), 8000)
check("orders.csv の行数", len(orders), 60061)
check("reviews.csv の行数", len(reviews), 14467)
check("books の列数", books.shape[1], 5)
check("customers の列数", customers.shape[1], 5)
check("orders の列数", orders.shape[1], 8)
check("reviews の列数", reviews.shape[1], 7)
check("books.book_id の一意な数", books["book_id"].nunique(), 600)
check("customers.customer_id の一意な数", customers["customer_id"].nunique(), 8000)
check("orders.order_id の一意な数（生）", orders["order_id"].nunique(), 60031)
check("reviews.order_id の一意な数", reviews["order_id"].nunique(), 14467)
check("reviews.review_id の一意な数", reviews["review_id"].nunique(), 14467)
check("重複排除後の orders の行数", len(orders_dedup), 60031)

# 2. 多対一の結合（右が一意なので行は増えない）
enriched = orders_dedup.merge(books, on="book_id", how="inner", validate="many_to_one")
check("orders_dedup + books の行数", len(enriched), 60031)
check("orders_dedup + books の列数", enriched.shape[1], 12)
check(
    "増えた列（books の残りの 4 列）",
    list(enriched.columns[-4:]),
    ["category", "price", "pages", "published_year"],
)
check("結合後の category の欠損", int(enriched["category"].isna().sum()), 0)


def revenue(df: pd.DataFrame) -> float:
    """本書の共通ルール：行ごとに丸めず、合計してから整数にする。"""
    return float((df["unit_price"] * df["quantity"] * (1 - df["discount_rate"])).sum())


valid = orders_dedup.loc[orders_dedup["is_canceled"] == 0]
canceled = orders_dedup.loc[orders_dedup["is_canceled"] == 1]
check("有効注文（重複・キャンセル除外）の件数", len(valid), 57869)
check("キャンセル注文の件数（重複排除後）", len(canceled), 2162)
check("有効 + キャンセル = 重複排除後の行数", len(valid) + len(canceled) == len(orders_dedup), True)
valid_enriched = valid.merge(books, on="book_id", how="inner", validate="many_to_one")
check("売上（結合前）の表示", f"{revenue(valid):,.0f}", "127,104,442")
check("売上（結合後）の表示", f"{revenue(valid_enriched):,.0f}", "127,104,442")

# 3. キー名が違うとき（left_on / right_on）はキーの列が 2 本残る
renamed = books.rename(columns={"book_id": "id"})
by_names = orders_dedup.merge(renamed, left_on="book_id", right_on="id", how="inner")
check("left_on / right_on で結合した行数", len(by_names), 60031)
check("left_on / right_on で結合した列数", by_names.shape[1], 13)
check("book_id と id が一致する行数", int((by_names["book_id"] == by_names["id"]).sum()), 60031)

# 4. 同名列の衝突（suffixes）と、必要な列だけに絞る書き方
with_orders = reviews.merge(orders_dedup, on="order_id", how="inner")
check("reviews + orders_dedup の行数", len(with_orders), 14467)
check("reviews + orders_dedup の列数", with_orders.shape[1], 14)
check(
    "衝突して _x / _y が付いた列",
    [c for c in with_orders.columns if c.startswith(("customer_id", "book_id"))],
    ["customer_id_x", "book_id_x", "customer_id_y", "book_id_y"],
)
check(
    "衝突列を末尾一致で抽出した場合（練習問題の書き方）",
    [c for c in with_orders.columns if c.endswith(("_x", "_y"))],
    ["customer_id_x", "book_id_x", "customer_id_y", "book_id_y"],
)
needed = ["order_id", "ordered_at", "quantity", "unit_price", "discount_rate", "is_canceled"]
slim = reviews.merge(orders_dedup[needed], on="order_id", how="inner", validate="one_to_one")
check("必要な列だけに絞った結合の行数", len(slim), 14467)
check("必要な列だけに絞った結合の列数", slim.shape[1], 12)

# 5. 4 種類の how（片側にしかないキーがあると初めて差が出る）
expected_join = {
    "inner": (60031, 7654, 0),
    "left": (60377, 8000, 346),
    "right": (60031, 7654, 0),
    "outer": (60377, 8000, 346),
}
for how, expected in expected_join.items():
    joined = customers.merge(orders_dedup, on="customer_id", how=how)
    actual = (len(joined), joined["customer_id"].nunique(), int(joined["order_id"].isna().sum()))
    check(f"how={how}（行数・顧客数・order_id が NaN の行）", actual, expected)

buyers = orders_dedup["customer_id"].nunique()
no_orders = len(customers) - buyers
check("注文が 1 件以上ある顧客の数", buyers, 7654)
check("注文が 1 件もない顧客の数", no_orders, 346)
left_join = customers.merge(orders_dedup, on="customer_id", how="left")
check("left 結合の行数の検算", len(orders_dedup) + no_orders == len(left_join), True)
check("顧客に注文を左結合したときの増加行数", len(left_join) - len(customers), 52377)

# 6. NaN が混ざると数値列の型が変わる（int64 → float64）
check("結合前の quantity の型", str(orders_dedup["quantity"].dtype), "int64")
check("left 結合後の quantity の型", str(left_join["quantity"].dtype), "float64")
check("left 結合後の order_id の欠損", int(left_join["order_id"].isna().sum()), 346)
print(f"---  left 結合後の order_id の型（参考）: {left_join['order_id'].dtype}")

# 7. indicator=True でどちら側にしかないキーを数える
flagged = orders_dedup.merge(
    reviews[["order_id", "rating"]], on="order_id", how="left", indicator=True
)
check("indicator: both", int((flagged["_merge"] == "both").sum()), 14467)
check("indicator: left_only", int((flagged["_merge"] == "left_only").sum()), 45564)
check("indicator: right_only", int((flagged["_merge"] == "right_only").sum()), 0)
check("indicator: 合計が orders_dedup の行数と同じ", len(flagged), 60031)
check("left_only + both = 60,031", 45564 + 14467 == len(orders_dedup), True)

# 8. 本章の山場：重複を落とさずに結合すると 11 行こっそり増える
naive = reviews.merge(orders, on="order_id", how="inner")
safe = reviews.merge(orders_dedup, on="order_id", how="inner")
check("reviews + orders（生）の行数", len(naive), 14478)
check("増えた行数", len(naive) - len(reviews), 11)
check("reviews + orders（重複排除）の行数", len(safe), 14467)
check("二重に現れた review_id の数", int(naive["review_id"].duplicated().sum()), 11)
dup_ids = orders.loc[orders.duplicated(subset="order_id"), "order_id"]
check("orders 側で重複していた注文の数", len(dup_ids), 30)
check("そのうちレビューがあった注文の数", int(reviews["order_id"].isin(dup_ids).sum()), 11)

# 9. 小さな表で直積を再現する
left_toy = pd.DataFrame({"key": ["A", "A", "B"], "left_val": [1, 2, 3]})
right_toy = pd.DataFrame({"key": ["A", "A", "C"], "right_val": [10, 20, 30]})
check("toy: how=inner の行数", len(left_toy.merge(right_toy, on="key", how="inner")), 4)
check("toy: how=outer の行数", len(left_toy.merge(right_toy, on="key", how="outer")), 6)
check("toy: how=cross の行数", len(left_toy.merge(right_toy, how="cross")), 9)

# 10. validate でキーの重複を機械に見張らせる
try:
    reviews.merge(orders, on="order_id", how="inner", validate="many_to_one")
    merge_error_msg = "（例外は出なかった）"
except MergeError as exc:
    # 例外文の 2 行目以降には重複キーの一覧が続くため、1 行目だけを比較する
    merge_error_msg = str(exc).splitlines()[0]
check(
    "validate=many_to_one が出すメッセージ",
    merge_error_msg,
    "Merge keys are not unique in right dataset; not a many-to-one merge",
)
checked = reviews.merge(orders_dedup, on="order_id", how="inner", validate="one_to_one")
check("重複排除後は validate=one_to_one が通る", len(checked), 14467)

# 11. キーの型違い（ValueError）と、書式違い（静かに 0 件）
str_key = pd.DataFrame({"book_id": ["B0001", "B0002"], "memo": ["a", "b"]})
int_key = pd.DataFrame({"book_id": [1, 2], "price": [3200, 1800]})
try:
    str_key.merge(int_key, on="book_id", how="inner")
    dtype_msg = "（例外は出なかった）"
except ValueError as exc:
    dtype_msg = f"{str(exc).split('. ')[0]}."
    print(f"---  型違いの結合で出た全文（参考）: {exc}")
check(
    "型違いのキーで出るメッセージの 1 文目",
    dtype_msg,
    "You are trying to merge on str and int64 columns for key 'book_id'.",
)
zero_padded = pd.DataFrame({"book_id": ["1", "2"], "price": [3200, 1800]})
check("書式が違うキーの結合結果", len(str_key.merge(zero_padded, on="book_id", how="inner")), 0)

# 12. concat（縦に積む）
rebuilt = pd.concat([valid, canceled], ignore_index=True)
check("concat で戻した行数", len(rebuilt), 60031)
check("concat で戻した列数", rebuilt.shape[1], 8)
head3 = orders_dedup.reset_index(drop=True).head(3)
stacked = pd.concat([head3, head3])
check("ignore_index なしのラベル", stacked.index.tolist(), [0, 1, 2, 0, 1, 2])
check("重複したラベルの数", int(stacked.index.duplicated().sum()), 3)
check(
    "ignore_index=True のラベル",
    pd.concat([head3, head3], ignore_index=True).index.tolist(),
    [0, 1, 2, 3, 4, 5],
)
a = pd.DataFrame({"book_id": ["B0001"], "price": [3200]})
b = pd.DataFrame({"book_id": ["B0002"], "pages": [420]})
filled = pd.concat([a, b], ignore_index=True)
check("列がずれた concat の形", filled.shape, (2, 3))
check("列がずれた concat の列", list(filled.columns), ["book_id", "price", "pages"])
check("列がずれた concat の NaN の数", int(filled.isna().sum().sum()), 2)

# 13. axis=1 の concat は位置で並べる（merge はキーで並べる）
c_left = pd.DataFrame({"key": ["A", "B"], "v": [1, 2]})
c_right = pd.DataFrame({"key": ["B", "A"], "w": [30, 40]})
wide = pd.concat([c_left, c_right], axis=1)
by_key = c_left.merge(c_right, on="key", how="inner")
check("concat(axis=1) で key=A の行に付く w", int(wide["w"].iloc[0]), 30)
check(
    "merge(on=key) で key=A の行に付く w",
    int(by_key.loc[by_key["key"] == "A", "w"].item()),
    40,
)

# 14. 練習問題（孤児キーを自分で作る）で出る数値
orphan = orders_dedup.head(5).copy()
orphan.loc[:, "book_id"] = "B9999"
orphan_outer = orphan.merge(books, on="book_id", how="outer", indicator=True)
check("孤児キー: outer の行数", len(orphan_outer), 605)
check("孤児キー: left_only", int((orphan_outer["_merge"] == "left_only").sum()), 5)
check("孤児キー: right_only", int((orphan_outer["_merge"] == "right_only").sum()), 600)
check("孤児キー: both", int((orphan_outer["_merge"] == "both").sum()), 0)
check("孤児キー: inner の行数", len(orphan.merge(books, on="book_id", how="inner")), 0)
orphan_left = orphan.merge(books, on="book_id", how="left", validate="many_to_one")
check("孤児キー: left の行数", len(orphan_left), 5)
check("孤児キー: left 結合後の price の欠損", int(orphan_left["price"].isna().sum()), 5)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 5 のすべての検証に成功しました。")
