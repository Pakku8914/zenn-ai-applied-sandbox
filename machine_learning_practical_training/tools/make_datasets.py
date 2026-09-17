"""本書で使うデータセットを決定的に生成する（乱数シードと基準日を固定）。

使い方: docker compose exec lab python tools/make_datasets.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20260908
# 「今日」を固定する。日付から特徴量を作る章でも結果がぶれないようにするため
REFERENCE_DATE = pd.Timestamp("2026-09-01")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

REGIONS = ["東京", "大阪", "愛知", "福岡", "北海道", "宮城", "広島"]
CATEGORIES = ["技術書", "ビジネス", "小説", "実用書", "児童書"]
CHANNELS = ["検索", "SNS", "メルマガ", "紹介"]


def make_books(rng: np.random.Generator) -> pd.DataFrame:
    """書籍マスタ。価格・ページ数・カテゴリを持つ"""
    n = 600
    category = rng.choice(CATEGORIES, size=n, p=[0.30, 0.22, 0.24, 0.16, 0.08])
    # カテゴリごとに価格帯が違う（カテゴリを使うと価格が説明できる、という構造を仕込む）
    base = pd.Series(category).map(
        {"技術書": 3200, "ビジネス": 1800, "小説": 900, "実用書": 1500, "児童書": 1100}
    ).to_numpy()
    price = np.round((base * rng.lognormal(0.0, 0.18, n)) / 10).astype(int) * 10
    pages = np.clip((price / 6 + rng.normal(0, 40, n)).astype(int), 80, 900)
    return pd.DataFrame(
        {
            "book_id": [f"B{i:04d}" for i in range(1, n + 1)],
            "category": category,
            "price": price,
            "pages": pages,
            "published_year": rng.integers(2015, 2027, n),
        }
    )


def make_customers(rng: np.random.Generator) -> pd.DataFrame:
    """顧客マスタ。地域には意図的に欠損を混ぜてある（前処理の章で扱う）"""
    n = 8000
    signup_offset = rng.integers(0, 975, n)  # 2024-01-01 〜 2026-08-31
    signup_date = pd.Timestamp("2024-01-01") + pd.to_timedelta(signup_offset, unit="D")
    region = rng.choice(REGIONS, size=n, p=[0.34, 0.16, 0.12, 0.11, 0.09, 0.09, 0.09]).astype(object)
    # 5% を欠損にする。「未入力」を意味する空欄で、ランダムではない欠損ではない
    missing = rng.random(n) < 0.05
    region[missing] = np.nan
    return pd.DataFrame(
        {
            "customer_id": [f"C{i:05d}" for i in range(1, n + 1)],
            "signup_date": signup_date,
            "birth_year": np.clip(rng.normal(1988, 13, n).astype(int), 1940, 2012),
            "region": region,
            "channel": rng.choice(CHANNELS, size=n, p=[0.42, 0.28, 0.18, 0.12]),
        }
    )


def make_orders(rng: np.random.Generator, customers: pd.DataFrame, books: pd.DataFrame) -> pd.DataFrame:
    """注文明細。1 顧客が複数回買う。キャンセル・外れ値・重複行を含む"""
    # 購入回数は少数の heavy user が全体を押し上げる形にする（現実のロングテール）
    counts = rng.poisson(rng.gamma(2.0, 3.75, len(customers)))
    customer_ids = np.repeat(customers["customer_id"].to_numpy(), counts)
    signup = np.repeat(customers["signup_date"].to_numpy(), counts)
    n = len(customer_ids)

    # 登録日から基準日までのどこかで注文する
    span_days = (REFERENCE_DATE.to_numpy() - signup) / np.timedelta64(1, "D")
    ordered_at = signup + (rng.random(n) * span_days * np.timedelta64(1, "D"))

    book_idx = rng.integers(0, len(books), n)
    unit_price = books["price"].to_numpy()[book_idx]
    discount = rng.choice([0.0, 0.05, 0.10, 0.20], size=n, p=[0.55, 0.20, 0.15, 0.10])

    quantity = rng.choice([1, 2, 3], size=n, p=[0.82, 0.14, 0.04])
    # 法人のまとめ買いを模した外れ値を 0.2% だけ混ぜる（外れ値検出の章で扱う）
    bulk = rng.random(n) < 0.002
    quantity[bulk] = rng.integers(15, 40, bulk.sum())

    # キャンセルは完全な偶然ではなく、金額・まとめ買い・流入経路・登録直後かどうかで
    # 起こりやすさが変わる。予測できる構造を持たせるため、確率をロジットで組み立てる
    channel = np.repeat(customers["channel"].to_numpy(), counts)
    days_since_signup = (ordered_at - signup) / np.timedelta64(1, "D")
    logit = (
        -4.80
        + 0.00095 * (unit_price - 1800)      # 高額な注文はキャンセルされやすい
        + 0.140 * quantity                   # まとめ買いは取り消しが増える
        + 1.30 * (channel == "SNS")          # 衝動的な流入経路
        + 1.80 * (days_since_signup < 7)     # 登録直後の様子見の注文
        + 0.90 * (discount == 0.20)          # 大きな値引きに釣られた注文
    )
    cancel_prob = 1.0 / (1.0 + np.exp(-logit))

    orders = pd.DataFrame(
        {
            "order_id": [f"O{i:06d}" for i in range(1, n + 1)],
            "customer_id": customer_ids,
            "book_id": books["book_id"].to_numpy()[book_idx],
            "ordered_at": pd.to_datetime(ordered_at).round("s"),
            "quantity": quantity,
            "unit_price": unit_price,
            "discount_rate": discount,
            "is_canceled": (rng.random(n) < cancel_prob).astype(int),
        }
    )

    # 同じ注文が二重に登録された事故を再現する（重複排除の章で扱う）
    dup = orders.sample(n=30, random_state=SEED)
    return pd.concat([orders, dup], ignore_index=True).sort_values("ordered_at").reset_index(drop=True)


def make_reviews(rng: np.random.Generator, orders: pd.DataFrame, books: pd.DataFrame) -> pd.DataFrame:
    """レビュー。星はカテゴリ・価格・ページ数・レビュー本文の長さに依存する"""
    valid = orders.loc[orders["is_canceled"] == 0].drop_duplicates(subset="order_id")
    reviewed = valid.sample(frac=0.25, random_state=SEED).reset_index(drop=True)
    reviewed = reviewed.merge(books[["book_id", "category", "pages", "published_year"]], on="book_id", how="left")
    n = len(reviewed)

    body_length = np.clip(rng.lognormal(4.2, 0.7, n).astype(int), 5, 2000)

    # 星を決める「見えない満足度」を組み立てる。予測モデルが学習できる構造をここで作っている
    category_effect = reviewed["category"].map(
        {"技術書": 0.45, "ビジネス": 0.05, "小説": 0.30, "実用書": -0.25, "児童書": 0.40}
    ).to_numpy()
    latent = (
        3.55
        + category_effect
        - 0.00055 * (reviewed["unit_price"].to_numpy() - 1800)  # 高い本は期待値も上がる
        + 0.0015 * reviewed["pages"].to_numpy()                  # 読み応えがあると満足度が上がる
        - 0.0024 * body_length                                   # 長文のレビューは不満の表明が多い
        + rng.normal(0, 0.38, n)
    )
    rating = np.clip(np.round(latent), 1, 5).astype(float)
    rating[rng.random(n) < 0.02] = np.nan  # 星だけ未入力のレビュー

    return pd.DataFrame(
        {
            "review_id": [f"R{i:06d}" for i in range(1, n + 1)],
            "order_id": reviewed["order_id"],
            "customer_id": reviewed["customer_id"],
            "book_id": reviewed["book_id"],
            "reviewed_at": reviewed["ordered_at"] + pd.to_timedelta(rng.integers(1, 30, n), unit="D"),
            "rating": rating,
            "body_length": body_length,
        }
    )


def main() -> None:
    rng = np.random.default_rng(SEED)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    books = make_books(rng)
    customers = make_customers(rng)
    orders = make_orders(rng, customers, books)
    reviews = make_reviews(rng, orders, books)

    for name, df in [
        ("books", books),
        ("customers", customers),
        ("orders", orders),
        ("reviews", reviews),
    ]:
        path = DATA_DIR / f"{name}.csv"
        df.to_csv(path, index=False)
        print(f"{path.name:15} {len(df):>7} 行  {len(df.columns)} 列")

    print(f"\n基準日          : {REFERENCE_DATE.date()}")
    print(f"乱数シード      : {SEED}")


if __name__ == "__main__":
    main()
