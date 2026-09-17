"""欠損の棚卸し ― どの列に、どれだけ欠損があるかを最初に数える。

使い方:
    docker compose exec lab python src/session11/missing_overview.py
"""

from __future__ import annotations

import pandas as pd

from common import load_customers, load_reviews, missing_report


def print_report(name: str, df: pd.DataFrame) -> None:
    """欠損のある列だけを「件数と率」で報告する。"""
    print(f"■ {name}: {len(df):,} 行 × {df.shape[1]} 列")
    report = missing_report(df)
    if report.empty:
        print("  欠損のある列はありません")
    for column, row in report.iterrows():
        print(f"  {column}: 欠損 {int(row['欠損数']):,} 件（{row['欠損率']:.2%}）")


def main() -> None:
    customers = load_customers()
    print_report("customers", customers)
    filled_count = int(customers["region"].count())
    print(
        f"  region の count（欠損を除いた件数）: {filled_count:,}"
        f" → 行数との差は {len(customers) - filled_count:,} 件"
    )

    reviews = load_reviews()
    print_report("reviews", reviews)

    # 結合すると欠損は「広がる」。顧客 1 人の欠損が、その人のレビュー全行に付いてくる
    analysed = reviews.dropna(subset=["rating"]).merge(
        customers[["customer_id", "region", "channel", "birth_year"]],
        on="customer_id",
        how="left",
        validate="many_to_one",
    )
    print(f"■ rating の欠損を落としたレビューに顧客を結合: {len(analysed):,} 行")
    n_missing = int(analysed["region"].isna().sum())
    print(f"  region の欠損: {n_missing:,} 件（{n_missing / len(analysed):.2%}）")


if __name__ == "__main__":
    main()
