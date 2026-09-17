"""セッション 6 の検証スクリプト。

「セッション6：集約する ― groupby と pivot」の本文・練習問題・解答に載せた
数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

金額は本書の規約どおり、丸めない列 revenue を 1 本だけ使って集計している。
  ・総額    : 合計してから整数に丸める（127,104,442 円）
  ・内訳    : 丸めない列を集計し、表示するときだけ整数に丸める
              （丸めた内訳を足すと 127,104,443 円で、総額と 1 円ずれる）

使い方:
    docker compose exec lab python src/session06/verify_06.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
TOLERANCE = 0.005

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    ok = actual == expected
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual}")
    if not ok:
        print(f"     期待値: {expected}")
        failures.append(label)


def check_close(label: str, actual: float, expected: float, tolerance: float = TOLERANCE) -> None:
    ok = abs(actual - expected) <= tolerance
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:.4f}")
    if not ok:
        print(f"     期待値: {expected:.4f} ± {tolerance}")
        failures.append(label)


missing_files = [
    name for name in ("books", "customers", "orders") if not (DATA_DIR / f"{name}.csv").exists()
]
if missing_files:
    print(f"NG   データが未生成です: {missing_files}")
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

# 1. 母集団（本書の規約：重複行とキャンセルを除く）
unique_orders = orders.drop_duplicates()
valid = unique_orders.loc[unique_orders["is_canceled"] == 0].copy()
valid["revenue"] = valid["unit_price"] * valid["quantity"] * (1 - valid["discount_rate"])

check("orders.csv の行数", len(orders), 60061)
check("重複を落とした注文", len(unique_orders), 60031)
check("有効注文（重複・キャンセル除外）", len(valid), 57869)
check("books.csv の行数", len(books), 600)
check("customers.csv の行数", len(customers), 8000)

# 2. 売上の総額（丸めるのは最後に一度だけ）
total = float(valid["revenue"].sum())
total_int = round(total)
row_rounded = int(valid["revenue"].round().sum())
check("売上の総額（合計してから整数にする）", total_int, 127104442)
check("売上の総額の表示", f"{total_int:,}", "127,104,442")
check("行ごとに丸めてから合計した額", row_rounded, 127104453)
check("行ごとに丸めた場合との差", row_rounded - total_int, 11)

# 3. 端数が出る条件（単価は 10 円単位・値引きは 0/5/10/20%）
check("1,010 円 × 1 冊 × 5% 引き", f"{1010 * 1 * (1 - 0.05):.2f}", "959.50")
check("1,010 円 × 1 冊 × 10% 引き", f"{1010 * 1 * (1 - 0.10):.2f}", "909.00")
check("値引き率の種類", sorted(valid["discount_rate"].unique().tolist()), [0.0, 0.05, 0.1, 0.2])
check("単価が 10 円単位であること", int((valid["unit_price"] % 10 != 0).sum()), 0)
# 丸めずに整数化（切り捨て）すると、四捨五入との差は 100 円を超える
check(
    "切り捨ては四捨五入より 100 円以上小さい",
    total_int - int(float((valid["revenue"] // 1).sum())) > 100,
    True,
)

# 4. カテゴリ別の集計（books を結合しても行数は増えない）
df = valid.merge(books[["book_id", "category", "price"]], on="book_id", how="left")
check("books を結合した後の行数", len(df), 57869)
check("category の種類", int(df["category"].nunique()), 5)

counts = df.groupby("category").size()
check(
    "groupby の既定の並び（キーの文字コード順）",
    counts.index.tolist(),
    ["ビジネス", "児童書", "実用書", "小説", "技術書"],
)
check(
    "注文数の多い順の並び",
    counts.sort_values(ascending=False).index.tolist(),
    ["技術書", "小説", "ビジネス", "実用書", "児童書"],
)
for category, expected_count in [
    ("技術書", 14397),
    ("小説", 13642),
    ("ビジネス", 13607),
    ("実用書", 11548),
    ("児童書", 4675),
]:
    check(f"{category} の注文数", int(counts.loc[category]), expected_count)
check("注文数の合計", int(counts.sum()), 57869)
check(
    "count と size が一致すること（欠損がない列だから）",
    df.groupby("category")["order_id"].count().tolist() == counts.tolist(),
    True,
)

# 5. agg（名前付き集約）でまとめた内訳の表
summary = df.groupby("category").agg(
    orders=("order_id", "count"),
    revenue=("revenue", "sum"),
    mean_quantity=("quantity", "mean"),
)
check("summary の列名", summary.columns.tolist(), ["orders", "revenue", "mean_quantity"])
check(
    "売上の多い順の並び",
    summary.sort_values("revenue", ascending=False).index.tolist(),
    ["技術書", "ビジネス", "実用書", "小説", "児童書"],
)
# 内訳は丸めない列を集計し、表示するときだけ整数に丸める
for category, expected_revenue in [
    ("技術書", 54993526),
    ("ビジネス", 29804128),
    ("実用書", 20639058),
    ("小説", 15696007),
    ("児童書", 5971724),
]:
    check(f"{category} の売上（表示用に丸めた値）", round(float(summary.loc[category, "revenue"])), expected_revenue)

breakdown_sum = int(sum(round(float(v)) for v in summary["revenue"]))
check("丸めた内訳を足した額", breakdown_sum, 127104443)
check("内訳の合計と総額の差", breakdown_sum - total_int, 1)
check("内訳の注文数の合計", int(summary["orders"].sum()), 57869)
check("売上が最大のカテゴリ（idxmax）", summary["revenue"].idxmax(), "技術書")
check("カテゴリ数（Series.size）", int(summary["revenue"].size), 5)

for category, expected_quantity in [
    ("小説", "1.280"),
    ("ビジネス", "1.250"),
    ("実用書", "1.249"),
    ("技術書", "1.237"),
    ("児童書", "1.230"),
]:
    check(
        f"{category} の平均数量",
        f"{float(summary.loc[category, 'mean_quantity']):.3f}",
        expected_quantity,
    )

check("売上が 2,000 万円を超えるカテゴリ数", int((summary["revenue"] > 20_000_000).sum()), 3)
check("注文数が 1 万件を超えるカテゴリ数", int((summary["orders"] > 10_000).sum()), 4)

# 6. 平均価格は books マスタ側で数える
mean_price = books.groupby("category")["price"].mean().round()
check(
    "平均価格の高い順の並び",
    mean_price.sort_values(ascending=False).index.tolist(),
    ["技術書", "ビジネス", "実用書", "児童書", "小説"],
)
for category, expected_price in [
    ("技術書", 3247),
    ("ビジネス", 1836),
    ("実用書", 1497),
    ("児童書", 1090),
    ("小説", 939),
]:
    check(f"{category} の平均価格", int(mean_price.loc[category]), expected_price)

# 7. 階層になった列名（agg にリストを渡した場合）
multi = df.groupby("category")[["quantity"]].agg(["count", "mean"])
check("階層になった列名", multi.columns.tolist(), [("quantity", "count"), ("quantity", "mean")])

# 8. 顧客数の 3 通りの数え方と、顧客あたりの売上
ordered_customers = unique_orders["customer_id"].nunique()
active_customers = valid["customer_id"].nunique()
check("① 全顧客", len(customers), 8000)
check("② 注文が 1 件以上ある顧客", ordered_customers, 7654)
check("③ 有効注文が 1 件以上ある顧客", active_customers, 7629)
check("注文が 1 件もない顧客", len(customers) - ordered_customers, 346)
check("② と ③ の差（キャンセルだけの顧客）", ordered_customers - active_customers, 25)

by_customer = valid.groupby("customer_id").agg(
    orders=("order_id", "count"),
    revenue=("revenue", "sum"),
)
check("顧客単位に集約した行数", len(by_customer), 7629)
check("顧客あたり売上の平均", f"{float(by_customer['revenue'].mean()):,.1f}", "16,660.7")
check("顧客あたり売上の中央値", f"{float(by_customer['revenue'].median()):,.1f}", "13,148.0")
check(
    "平均 > 中央値（右に裾が長い）",
    bool(by_customer["revenue"].mean() > by_customer["revenue"].median()),
    True,
)
check("集約のキーはインデックスになる", by_customer.index.name, "customer_id")
check("集約後の列名", by_customer.columns.tolist(), ["orders", "revenue"])
check(
    "reset_index 後の列名",
    by_customer.reset_index().columns.tolist(),
    ["customer_id", "orders", "revenue"],
)
check("顧客ごとの注文数の合計", int(by_customer["orders"].sum()), 57869)

# 9. pivot_table（2 軸のクロス集計）と、欠損したキーが消える問題
joined = valid.merge(
    customers[["customer_id", "region", "channel"]], on="customer_id", how="left"
)
check("顧客属性を結合した後の行数", len(joined), 57869)

pivot = joined.pivot_table(
    index="region", columns="channel", values="revenue", aggfunc="sum"
)
check("pivot の形", pivot.shape, (7, 4))
check(
    "pivot の行ラベル",
    pivot.index.tolist(),
    ["北海道", "大阪", "宮城", "広島", "愛知", "東京", "福岡"],
)
check("pivot の列ラベル", pivot.columns.tolist(), ["SNS", "メルマガ", "検索", "紹介"])
check("空のセルがないこと", int(pivot.isna().sum().sum()), 0)

top_region, top_channel = pivot.stack().idxmax()
check("最大のセルの位置", (top_region, top_channel), ("東京", "検索"))
check("最大のセルの値（表示用に丸めた値）", round(float(pivot.loc[top_region, top_channel])), 18194833)

in_table = float(pivot.to_numpy().sum())
missing_revenue = float(joined.loc[joined["region"].isna(), "revenue"].sum())
check("region が未入力の売上（表に現れない）", round(missing_revenue), 6492330)
check(
    "表の全セル + 未入力分 = 総額",
    abs(in_table + missing_revenue - total) < 0.01,
    True,
)
check("region の欠損（顧客マスタ）", int(customers["region"].isna().sum()), 392)

mean_pivot = joined.pivot_table(index="region", columns="channel", values="revenue")
check(
    "aggfunc を省略すると平均になる（合計より小さい）",
    bool(mean_pivot.loc[top_region, top_channel] < pivot.loc[top_region, top_channel]),
    True,
)

# 10. transform（集約結果を元の行数のまま戻す）
toy = pd.DataFrame({"customer": ["A", "A", "B"], "amount": [100, 300, 500]})
check("toy の集約", toy.groupby("customer")["amount"].sum().to_dict(), {"A": 400, "B": 500})
check(
    "toy の transform",
    toy.groupby("customer")["amount"].transform("sum").tolist(),
    [400, 400, 500],
)

work = valid.copy()
work["customer_mean"] = work.groupby("customer_id")["revenue"].transform("mean")
work["diff_from_mean"] = work["revenue"] - work["customer_mean"]
work["customer_total"] = work.groupby("customer_id")["revenue"].transform("sum")
work["share"] = work["revenue"] / work["customer_total"]
check("transform の後も行数は変わらない", len(work), 57869)
check("差の合計は 0", f"{abs(float(work['diff_from_mean'].sum())):.0f}", "0")
check("シェアの合計は顧客数と一致", f"{float(work['share'].sum()):,.1f}", "7,629.0")

mean_table = (
    work.groupby("customer_id")["revenue"].mean().rename("mean_by_merge").reset_index()
)
merged = work.merge(mean_table, on="customer_id", how="left")
check("merge で作り直しても同じ値になる", bool(
    float((merged["customer_mean"] - merged["mean_by_merge"]).abs().max()) < 1e-9
), True)
check("merge しても行数は増えない", len(merged), 57869)

# 11. size / count / mean / sum と欠損の扱い（小さな表で確かめる）
na_toy = pd.DataFrame({"g": ["A", "A", "B"], "x": [1.0, None, 3.0]})
check("size（行数を数える）", na_toy.groupby("g").size().to_dict(), {"A": 2, "B": 1})
check("count（欠損を除いて数える）", na_toy.groupby("g")["x"].count().to_dict(), {"A": 1, "B": 1})
check("mean（欠損を無視する）", na_toy.groupby("g")["x"].mean().to_dict(), {"A": 1.0, "B": 3.0})
check("sum（欠損を 0 として扱う）", na_toy.groupby("g")["x"].sum().to_dict(), {"A": 1.0, "B": 3.0})

region_toy = pd.DataFrame({"region": ["東京", None, "大阪"], "revenue": [100, 200, 300]})
check(
    "キーが欠損した行は既定で落ちる",
    int(region_toy.groupby("region")["revenue"].sum().sum()),
    400,
)
check(
    "dropna=False なら落ちない",
    int(region_toy.groupby("region", dropna=False)["revenue"].sum().sum()),
    600,
)

# 12. 本文の「よくあるエラー」が実際にそのエラーになること
try:
    _ = counts["category"]
    key_error = False
except KeyError:
    key_error = True
check("集約結果に元のキー名でアクセスすると KeyError", key_error, True)

try:
    _ = df.groupby("category").mean()
    type_error = False
except TypeError:
    type_error = True
check("文字列の列を含めて mean() すると TypeError", type_error, True)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 6 のすべての検証に成功しました。")
