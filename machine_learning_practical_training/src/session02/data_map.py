"""本書で使う 4 つのデータファイルの関係（地図）を確かめる。

このスクリプトは「データを説明する」側の作業だけを行います。
予測はしません。まず手元に何があるのかを数え上げるのが目的です。

使い方:
    docker compose exec lab python src/session02/data_map.py
"""

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

books = pd.read_csv(DATA_DIR / "books.csv")
customers = pd.read_csv(DATA_DIR / "customers.csv", parse_dates=["signup_date"])
orders = pd.read_csv(DATA_DIR / "orders.csv", parse_dates=["ordered_at"])
reviews = pd.read_csv(DATA_DIR / "reviews.csv", parse_dates=["reviewed_at"])

# 1. まず「形」を見る。行数と列数が分かれば、データの規模感がつかめる
print("■ 4 つのファイルの形")
for name, df in [("books", books), ("customers", customers), ("orders", orders), ("reviews", reviews)]:
    print(f"{name:9}: {len(df):,} 行 × {len(df.columns)} 列")

# 2. キーで本当につながるかを確かめる。つながらない行があれば、それ自体が発見
print("\n■ キーはつながっているか（照合できない行を数える）")
lost_customer = int((~orders["customer_id"].isin(customers["customer_id"])).sum())
lost_book = int((~orders["book_id"].isin(books["book_id"])).sum())
lost_order = int((~reviews["order_id"].isin(orders["order_id"])).sum())
print(f"customers に存在しない customer_id を持つ注文: {lost_customer} 件")
print(f"books に存在しない book_id を持つ注文: {lost_book} 件")
print(f"orders に存在しない order_id を持つレビュー: {lost_order} 件")

# 3. つながっていても「相手がいない」側はある。ここを見落とすと平均を取り違える
print("\n■ つながっていても「無い」ものはある")
unique_orders = orders.drop_duplicates("order_id")
no_order = int((~customers["customer_id"].isin(orders["customer_id"])).sum())
no_review = int((~unique_orders["order_id"].isin(reviews["order_id"])).sum())
print(f"注文が 1 件もない顧客: {no_order} 人")
print(f"レビューが付いていない注文: {no_review:,} 件")

# 4. 売上を数える前に落とすもの（本書の共通ルール）
#    重複行 → キャンセル注文 の順で除き、金額は行ごとに丸めず合計してから整数にする
print("\n■ 売上を数える前に落とすもの（本書の共通ルール）")
valid = unique_orders.loc[unique_orders["is_canceled"] == 0]
revenue = (valid["unit_price"] * valid["quantity"] * (1 - valid["discount_rate"])).sum()
print(f"注文の行数（読み込んだまま）: {len(orders):,} 行")
print(f"完全に重複した行: {int(orders.duplicated().sum())} 行")
print(f"重複を除いた注文: {len(unique_orders):,} 件")
print(f"キャンセル率: {unique_orders['is_canceled'].mean():.2%}")
print(f"有効な注文（重複とキャンセルを除く）: {len(valid):,} 件")
print(f"売上合計: {revenue:,.0f} 円")
