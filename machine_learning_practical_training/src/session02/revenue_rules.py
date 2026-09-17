"""売上の数え方のルールを変えると、金額がどう変わるかを並べて見る。

本書の共通ルールは「重複行を除く → キャンセル注文を除く → 行ごとに丸めずに合計する」です。
このスクリプトは、そのルールを外した場合と並べて比べます。

使い方:
    docker compose exec lab python src/session02/revenue_rules.py
"""

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

orders = pd.read_csv(DATA_DIR / "orders.csv", parse_dates=["ordered_at"])


def amount(df: pd.DataFrame) -> pd.Series:
    """行ごとの金額（単価 × 数量 × 値引き後の割合）。ここでは丸めない"""
    return df["unit_price"] * df["quantity"] * (1 - df["discount_rate"])


unique_orders = orders.drop_duplicates("order_id")
valid = unique_orders.loc[unique_orders["is_canceled"] == 0]

print("■ 除外ルールを変えると売上はどう変わるか")
print(f"① 何も除外しない（{len(orders):,} 行）: {amount(orders).sum():,.0f} 円")
print(f"② 重複だけを除いた（{len(unique_orders):,} 件）: {amount(unique_orders).sum():,.0f} 円")
print(f"③ 重複とキャンセルを除いた（{len(valid):,} 件）: {amount(valid).sum():,.0f} 円  ← 本書の売上")

print("\n■ 除外した内訳")
print(f"完全に重複した行: {int(orders.duplicated().sum())} 行")
print(f"キャンセルされた注文: {len(unique_orders) - len(valid):,} 件")

print("\n■ 丸める順序でも値は変わる（どちらも③の 57,869 件が対象）")
print(f"行ごとに丸めてから合計: {amount(valid).round().sum():,.0f} 円")
print(f"合計してから丸める（本書のルール）: {amount(valid).sum():,.0f} 円")
