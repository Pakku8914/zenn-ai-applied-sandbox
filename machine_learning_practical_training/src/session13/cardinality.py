"""カテゴリ列の水準の数（カーディナリティ）を数え、One-Hot にしたときの列数を見積もる。

使い方:
    docker compose exec lab python src/session13/cardinality.py
"""

from __future__ import annotations

import pandas as pd

from common import load_books, load_customers, load_review_features


def levels(values: pd.Series) -> str:
    """水準を並べ替えて「A / B / C」の形にする（表示の順番が毎回同じになる）。"""
    return " / ".join(sorted(values.dropna().unique()))


def main() -> None:
    customers = load_customers()
    books = load_books()
    columns = {
        "region": customers["region"],
        "channel": customers["channel"],
        "category": books["category"],
        "book_id": books["book_id"],
    }

    print("■ カテゴリ列のカーディナリティ（水準の数）")
    print("列       | 水準の数 | 欠損の数")
    for name, values in columns.items():
        print(f"{name:<8} | {values.nunique():>8} | {int(values.isna().sum()):>8}")
    print()

    print("■ 水準の一覧（並べ替えて表示）")
    for name in ("region", "channel", "category"):
        print(f"{name:<8} : {levels(columns[name])}")
    ids = sorted(columns["book_id"])
    print(f"{'book_id':<8} : {ids[0]} / {ids[1]} / {ids[2]} ... {ids[-1]}")
    print()

    print("■ One-Hot にすると何列になるか")
    region_levels = columns["region"].nunique() + 1  # 欠損を「不明」という 1 水準として数える
    print(f"region を「不明」で埋めて channel と一緒に開く : {region_levels + columns['channel'].nunique()} 列")
    print(f"category を開く : {columns['category'].nunique()} 列")
    print(f"book_id を開く  : {columns['book_id'].nunique()} 列")
    print()

    df = load_review_features()
    print("■ 高評価分類に使う表（前章と同じ作り方）")
    print(f"行数            : {len(df):,}")
    print(f"category の水準 : {df['category'].nunique()}")
    print(f"book_id の水準  : {df['book_id'].nunique()}")


if __name__ == "__main__":
    main()
