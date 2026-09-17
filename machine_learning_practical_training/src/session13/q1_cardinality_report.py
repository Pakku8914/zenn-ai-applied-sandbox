"""問題1 の解答: カテゴリ列の棚卸し（水準の数・欠損・尺度・選ぶ変換）。

使い方:
    docker compose exec lab python src/session13/q1_cardinality_report.py
"""

from __future__ import annotations

import pandas as pd

from common import load_books, load_customers

HIGH_CARDINALITY = 50  # これ以上の水準を「高カーディナリティ」と呼ぶことにする


def levels(values: pd.Series) -> str:
    """水準を並べ替えて「A / B / C」の形にする。"""
    return " / ".join(sorted(values.dropna().unique()))


def main() -> None:
    customers = load_customers()
    books = load_books()
    plans = {
        "region": "名義尺度 | 欠損を「不明」で埋めて One-Hot",
        "channel": "名義尺度 | One-Hot",
        "category": "名義尺度 | 線形モデルは One-Hot / 木モデルは Label でもよい",
        "book_id": "名義尺度 | そのまま One-Hot にしない（列が増えすぎる）",
    }
    columns = {
        "region": customers["region"],
        "channel": customers["channel"],
        "category": books["category"],
        "book_id": books["book_id"],
    }

    print("■ カテゴリ列の棚卸し")
    print("列       | 水準の数 | 欠損の数 | 尺度     | 選ぶ変換")
    for name, values in columns.items():
        print(f"{name:<8} | {values.nunique():>8} | {int(values.isna().sum()):>8} | {plans[name]}")
    print()

    print("■ One-Hot にしたときの列数")
    region_levels = columns["region"].nunique() + 1  # 欠損を「不明」という 1 水準として数える
    print(f"region（不明を含む {region_levels} 水準）+ channel : {region_levels + columns['channel'].nunique()} 列")
    print(f"category : {columns['category'].nunique()} 列")
    print(f"book_id  : {columns['book_id'].nunique()} 列")
    print()

    print("■ 水準の一覧（並べ替えて表示）")
    for name in ("region", "channel", "category"):
        print(f"{name:<8} : {levels(columns[name])}")
    print()

    print("■ 判定")
    # 4 列とも「大小を比べられない名前」なので、順序尺度に当たる列は無い
    print(f"順序尺度の列           : なし（{len(columns)} 列すべて名義尺度）")
    high = [name for name, values in columns.items() if values.nunique() >= HIGH_CARDINALITY]
    print(f"高カーディナリティの列 : {' / '.join(high)}（{HIGH_CARDINALITY} 水準以上）")
    print("星（rating 1〜5）は順序尺度ですが、すでに数値なので変換は不要です")


if __name__ == "__main__":
    main()
