"""セッション 4 の検証スクリプト。

「セッション4：行と列を選ぶ ― 抽出・重複・並べ替え」の本文・練習問題・解答に
載せた数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session04/verify_04.py
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
WARNING_HEAD = "A value is being set on a copy of a DataFrame or Series through chained assignment."

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

# 1. 4 ファイルの行数（抽出の前提が崩れていないこと）
check("books.csv の行数", len(books), 600)
check("customers.csv の行数", len(customers), 8000)
check("orders.csv の行数", len(orders), 60061)
check("reviews.csv の行数", len(reviews), 14467)
check("orders.csv の列数", orders.shape[1], 8)

# 2. iloc（位置）と loc（ラベル）
first = orders.iloc[0]
check("iloc[0] の order_id", first["order_id"], "O045046")
check("iloc[0] の ordered_at の日付", str(first["ordered_at"].date()), "2024-01-09")
check("iloc[0] の quantity", int(first["quantity"]), 1)
check("loc[0] と iloc[0] が同じ行を指すこと", orders.loc[0, "order_id"] == first["order_id"], True)
check("loc[0:2] の行数（終端を含む）", len(orders.loc[0:2]), 3)
check("iloc[0:2] の行数（終端を含まない）", len(orders.iloc[0:2]), 2)
check("loc[0:2, 2 列] の形", orders.loc[0:2, ["order_id", "quantity"]].shape, (3, 2))

by_customer = orders.set_index("customer_id")
check("set_index 後の loc['C00001'] の行数", len(by_customer.loc["C00001"]), 9)

# 3. ブールインデックスと query
mask = orders["quantity"] >= 15
check("mask の dtype", str(mask.dtype), "bool")
check("quantity >= 15 の件数", int(mask.sum()), 118)
check("quantity の最大値", int(orders["quantity"].max()), 39)
check("mask で抽出した結果の形", orders.loc[mask].shape, (118, 8))
check("between(15, 39) の件数（境界を含む）", int(orders["quantity"].between(15, 39).sum()), 118)
check("否定した件数 + 元の件数 = 全行数", int((~mask).sum()) + int(mask.sum()) == len(orders), True)
check("customer_id == 'C00001' の件数", int((orders["customer_id"] == "C00001").sum()), 9)
check("isin(['C00001']) の件数", int(orders["customer_id"].isin(["C00001"]).sum()), 9)

both = orders.loc[(orders["quantity"] >= 15) & (orders["discount_rate"] == 0.2)]
queried = orders.query("quantity >= 15 and discount_rate == 0.2")
check("& で書いた複数条件の件数", len(both), 11)
check("query で書いた複数条件の件数", len(queried), 11)
check("& と query の結果が一致すること", both.equals(queried), True)
threshold = 15
check(
    "query に @ で変数を渡した結果",
    len(orders.query("quantity >= @threshold and discount_rate == 0.2")),
    11,
)

# 4. 重複行の検出と除去
check("完全重複行の件数", int(orders.duplicated().sum()), 30)
check("order_id で見た重複の件数", int(orders.duplicated(subset="order_id").sum()), 30)
unique_orders = orders.drop_duplicates()
check("drop_duplicates() 後の行数", len(unique_orders), 60031)
check("重複とキャンセルを除いた有効注文の件数", int((unique_orders["is_canceled"] == 0).sum()), 57869)

check("keep=False で残る「元の行とコピー」の行数", int(orders.duplicated(keep=False).sum()), 60)
check(
    "duplicated の件数 == 元の行数 - 重複除去後の行数",
    int(orders.duplicated().sum()) == len(orders) - len(unique_orders),
    True,
)

toy = pd.DataFrame({"order_id": ["O1", "O1", "O2"], "quantity": [1, 1, 2]})
check("toy の duplicated()", toy.duplicated().tolist(), [False, True, False])
check("toy の duplicated(keep='last')", toy.duplicated(keep="last").tolist(), [True, False, False])
check("toy の duplicated(keep=False)", toy.duplicated(keep=False).tolist(), [True, True, False])
check("toy の drop_duplicates() の行数", len(toy.drop_duplicates()), 2)
check("toy の drop_duplicates(keep=False) の行数", len(toy.drop_duplicates(keep=False)), 1)

# 5. 並べ替え
by_qty = orders.sort_values("quantity", ascending=False)
check("quantity 降順の先頭の quantity", int(by_qty.iloc[0]["quantity"]), 39)
recent = orders.sort_values(["customer_id", "ordered_at"], ascending=[True, False])
check("customer_id 昇順の先頭", recent.iloc[0]["customer_id"], "C00001")
check("並べ替えても元の先頭は変わらないこと", orders.iloc[0]["order_id"], "O045046")
check("reset_index(drop=True) 後の先頭ラベル", int(recent.reset_index(drop=True).index[0]), 0)
check("並べ替え後の先頭ラベルが 0 ではないこと", int(recent.index[0]) != 0, True)
c1_dates = recent.loc[recent["customer_id"] == "C00001", "ordered_at"]
check("C00001 の 9 件が日時の降順に並ぶこと", bool(c1_dates.is_monotonic_decreasing), True)
check("C00001 の抽出件数", len(c1_dates), 9)
bulk_sorted = orders.loc[mask].sort_values(["quantity", "ordered_at"], ascending=[False, True])
check("まとめ買いを注文数降順に並べた先頭の quantity", int(bulk_sorted.iloc[0]["quantity"]), 39)

# 6. チェーン代入（pandas 3.0 では「警告」で済み、代入は黙って捨てられる）
df = orders.copy()
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    df["quantity"][0] = 999
caught_names = sorted({w.category.__name__ for w in caught})
print(f"---  チェーン代入で出た警告: {caught_names}")
check("ChainedAssignmentError が出ること", "ChainedAssignmentError" in caught_names, True)
check(
    "警告文が想定の 1 文で始まること",
    any(str(w.message).startswith(WARNING_HEAD) for w in caught),
    True,
)
check("チェーン代入は反映されない（値は元のまま）", int(df.loc[0, "quantity"]), 1)

df.loc[0, "quantity"] = 999
check("loc での代入は反映される", int(df.loc[0, "quantity"]), 999)

df2 = orders.copy()
with warnings.catch_warnings(record=True):
    warnings.simplefilter("always")
    series = df2["quantity"]
    series[0] = 999
check("変数に受けた Series 側は書き換わる", int(series.iloc[0]), 999)
check("元の DataFrame は変わらない", int(df2.loc[0, "quantity"]), 1)

df3 = orders.copy()
df3.loc[df3["customer_id"] == "C00001", "quantity"] = 0
check("loc + 条件でまとめて代入した件数", int((df3["quantity"] == 0).sum()), 9)

# 7. 本文の「よくあるエラー」が実際にそのエラーになること
try:
    _ = orders["quantity"] >= 15 and orders["is_canceled"] == 0
    and_raises = False
except ValueError as exc:
    and_raises = "truth value of a Series is ambiguous" in str(exc)
check("and でつなぐと ValueError になること", and_raises, True)

high = orders.loc[mask]
try:
    _ = high.loc[0]
    loc_raises = False
except KeyError:
    loc_raises = True
check("抽出後に loc[0] が KeyError になること", loc_raises, True)
check("抽出後でも iloc[0] は取れること", int(high.iloc[0]["quantity"]) >= 15, True)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 4 のすべての検証に成功しました。")
