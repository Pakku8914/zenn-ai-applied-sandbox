"""問題1: 欠損の棚卸し ― どの列に、どれだけ欠損があるかを一覧にする。

使い方:
    docker compose exec lab python src/session11/q1_missing_report.py
"""

from __future__ import annotations

import pandas as pd

from common import load_customers, load_reviews, missing_report


def report(name: str, df: pd.DataFrame) -> None:
    """欠損のある列について「件数・率・count」を 1 行で報告する。"""
    print(f"■ {name}（{len(df):,} 行）")
    for column, row in missing_report(df).iterrows():
        print(
            f"  {column}: 欠損 {int(row['欠損数']):,} 件 / 欠損率 {row['欠損率']:.2%}"
            f" / count {int(df[column].count()):,}"
        )


def main() -> None:
    customers = load_customers()
    reviews = load_reviews()
    report("customers", customers)
    report("reviews", reviews)

    # count は欠損を数えない。だから「行数 - count」が欠損数になる
    print("■ 検算（行数 - count = 欠損数）")
    for name, series in [("region", customers["region"]), ("rating", reviews["rating"])]:
        total, count = len(series), int(series.count())
        print(f"  {name}: {total:,} - {count:,} = {total - count:,}"
              f" → {total - count == int(series.isna().sum())}")

    # 結合すると欠損は広がる。顧客 1 人の欠損が、その人のレビュー全行に付いてくる
    analysed = reviews.dropna(subset=["rating"]).merge(
        customers[["customer_id", "region"]], on="customer_id", how="left", validate="many_to_one"
    )
    rate = float(analysed["region"].isna().mean())
    master_rate = float(customers["region"].isna().mean())
    print(f"■ レビュー（{len(analysed):,} 行）に顧客を結合したあとの region")
    print(f"  欠損 {int(analysed['region'].isna().sum()):,} 件（{rate:.2%}）")
    print(f"  マスタの欠損率 {master_rate:.2%} より大きいか: {rate > master_rate}")


if __name__ == "__main__":
    main()
