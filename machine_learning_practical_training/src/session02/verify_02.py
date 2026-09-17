"""セッション 2 の本文・練習問題・解答に載せた数値を、この環境で再計算して照合する。

期待値と一致しない場合は非 0 で終了します（数値の食い違いを見逃さないため）。

使い方:
    docker compose exec lab python src/session02/verify_02.py
"""

from pathlib import Path

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
TOLERANCE = 0.005  # 指標の許容誤差

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


missing = [name for name in ("books", "customers", "orders", "reviews") if not (DATA_DIR / f"{name}.csv").exists()]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

books = pd.read_csv(DATA_DIR / "books.csv")
customers = pd.read_csv(DATA_DIR / "customers.csv", parse_dates=["signup_date"])
orders = pd.read_csv(DATA_DIR / "orders.csv", parse_dates=["ordered_at"])
reviews = pd.read_csv(DATA_DIR / "reviews.csv", parse_dates=["reviewed_at"])

# 1. data_map.py：4 ファイルの形
for name, df, rows, cols in [
    ("books", books, 600, 5),
    ("customers", customers, 8000, 5),
    ("orders", orders, 60061, 8),
    ("reviews", reviews, 14467, 7),
]:
    check(f"{name}.csv の行数", len(df), rows)
    check(f"{name}.csv の列数", len(df.columns), cols)

# 2. data_map.py：キーが照合できない行は 1 件もない
check(
    "customers に存在しない customer_id を持つ注文",
    int((~orders["customer_id"].isin(customers["customer_id"])).sum()),
    0,
)
check("books に存在しない book_id を持つ注文", int((~orders["book_id"].isin(books["book_id"])).sum()), 0)
check("orders に存在しない order_id を持つレビュー", int((~reviews["order_id"].isin(orders["order_id"])).sum()), 0)

# 3. data_map.py：相手がいない側（注文のない顧客・レビューのない注文）
unique_orders = orders.drop_duplicates("order_id")
check("注文が 1 件もない顧客", int((~customers["customer_id"].isin(orders["customer_id"])).sum()), 346)
check(
    "レビューが付いていない注文",
    int((~unique_orders["order_id"].isin(reviews["order_id"])).sum()),
    45564,
)

# 4. data_map.py：売上を数える前に落とすもの
valid = unique_orders.loc[unique_orders["is_canceled"] == 0]
check("完全に重複した行", int(orders.duplicated().sum()), 30)
check("重複を除いた注文", len(unique_orders), 60031)
check_close("キャンセル率", float(unique_orders["is_canceled"].mean()), 0.0360)
check("キャンセル率の表示", f"{unique_orders['is_canceled'].mean():.2%}", "3.60%")
check("有効な注文（重複とキャンセルを除く）", len(valid), 57869)
check("キャンセルされた注文", len(unique_orders) - len(valid), 2162)

amount = valid["unit_price"] * valid["quantity"] * (1 - valid["discount_rate"])
revenue = float(amount.sum())
check("売上合計の表示（円）", f"{revenue:,.0f}", "127,104,442")
check_close("売上合計（円・±1 円まで許容）", revenue, 127104442.0, tolerance=1.0)

# 5. revenue_rules.py：ルールを外すと必ず過大になる／丸める順序でずれる
gross = float((orders["unit_price"] * orders["quantity"] * (1 - orders["discount_rate"])).sum())
dedup_total = float((unique_orders["unit_price"] * unique_orders["quantity"] * (1 - unique_orders["discount_rate"])).sum())
check("① 何も除外しない合計は本書の売上より大きい", gross > revenue, True)
check("② 重複だけを除いた合計は本書の売上より大きい", dedup_total > revenue, True)
check("②（重複除去後）は①（生）より小さい", dedup_total < gross, True)
check_close(
    "行ごとに丸めてから合計（円・±1 円まで許容）",
    float(amount.round().sum()),
    127104453.0,
    tolerance=1.0,
)

# 6. analysis_tour.py：ステップ 2（データを見る）
check("星が未入力のレビュー", int(reviews["rating"].isna().sum()), 298)
check_close("星の平均", float(reviews["rating"].mean()), 3.9725)
star_counts = reviews["rating"].value_counts().sort_index()
for star, expected_count in [(1, 1), (2, 38), (3, 2558), (4, 9325), (5, 2247)]:
    check(f"星 {star} の件数", int(star_counts.loc[float(star)]), expected_count)

# 7. analysis_tour.py：ステップ 3（整える）
df = reviews.dropna(subset=["rating"]).merge(books, on="book_id", how="left")
check("星が入っているレビュー", len(df), 14169)
check("書籍の情報を足した後の列数", df.shape[1], 11)

# 8. analysis_tour.py：ステップ 4・5（モデル化と評価）
features = ["price", "pages", "body_length"]
y = (df["rating"] >= 4).astype(int)
check_close("高評価の割合（正例率）", float(y.mean()), 0.8167)
check("高評価の割合の表示", f"{y.mean():.0%}", "82%")

X_scaled = StandardScaler().fit_transform(df[features])
X_train, X_test, y_train, y_test = train_test_split(
    X_scaled, y, test_size=0.25, random_state=42, stratify=y
)
check("学習データの件数", len(X_train), 10626)
check("評価データの件数", len(X_test), 3543)
scaled_model = LogisticRegression(max_iter=1000).fit(X_train, y_train)
check_close(
    "analysis_tour.py / hello.py の ROC AUC（スケーリングあり）",
    roc_auc_score(y_test, scaled_model.predict_proba(X_test)[:, 1]),
    0.7271,
)

# 前章の check_env.py はスケーリングをしていないため、わずかに違う値になる
Xr_train, Xr_test, yr_train, yr_test = train_test_split(
    df[features], y, test_size=0.25, random_state=42, stratify=y
)
raw_model = LogisticRegression(max_iter=1000).fit(Xr_train, yr_train)
check_close(
    "check_env.py の ROC AUC（スケーリングなし）",
    roc_auc_score(yr_test, raw_model.predict_proba(Xr_test)[:, 1]),
    0.7269,
)

# 9. hello.py：カテゴリ別の平均価格
mean_price = books.groupby("category")["price"].mean().round()
for category, expected_price in [
    ("技術書", 3247),
    ("ビジネス", 1836),
    ("実用書", 1497),
    ("児童書", 1090),
    ("小説", 939),
]:
    check(f"{category} の平均価格", int(mean_price.loc[category]), expected_price)

# 10. leak_peek.py：本文の長さと星は負の相関（値そのものは本文に書かない）
check("body_length と rating の相関は負", bool(reviews["body_length"].corr(reviews["rating"]) < 0), True)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 2 のすべての検証に成功しました。")
