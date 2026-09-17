"""分散・標準偏差・四分位範囲を並べ、「ばらつき」の測り方の違いを確かめる。

使い方:
    docker compose exec lab python src/session09/spread_measures.py
"""

from __future__ import annotations

from common import load_orders, load_rated_reviews


def main() -> None:
    quantity = load_orders()["quantity"]
    rating = load_rated_reviews()["rating"]

    for name, series in [("quantity（60,031 行）", quantity), ("rating（14,169 件）", rating)]:
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        print(f"■ {name}")
        print(f"平均       : {series.mean():.4f}")
        print(f"分散       : {series.var():.4f}")
        print(f"標準偏差   : {series.std():.4f}")
        print(f"Q1 / Q3    : {q1:.1f} / {q3:.1f}")
        print(f"四分位範囲 : {q3 - q1:.1f}")
        print()


if __name__ == "__main__":
    main()
