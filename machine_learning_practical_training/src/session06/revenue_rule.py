"""本書の規約で売上を計算する。丸めるのは最後に一度だけ。

    docker compose exec lab python src/session06/revenue_rule.py
"""

from __future__ import annotations

from common import load_tables, valid_orders


def main() -> None:
    _books, _customers, orders = load_tables()
    unique_orders = orders.drop_duplicates()
    valid = valid_orders(orders)

    print("■ 母集団をそろえる（本書の規約）")
    print(f"読み込んだ注文    : {len(orders):,} 行")
    print(f"重複を落とすと    : {len(unique_orders):,} 行")
    print(f"キャンセルを除くと: {len(valid):,} 件（有効注文）")

    total = float(valid["revenue"].sum())        # 丸めない金額の合計
    row_rounded = int(valid["revenue"].round().sum())  # 行ごとに丸めてから合計

    print("\n■ 売上の総額（丸めるのは最後に一度だけ）")
    print(f"合計してから整数にする: {round(total):,} 円  ← 本書の売上")
    print(f"行ごとに丸めてから合計: {row_rounded:,} 円（11 円多い）")

    print("\n■ 端数はどこから来るのか（単価は 10 円単位）")
    print(f"1,010 円 × 1 冊 × 5% 引き : {1010 * 1 * (1 - 0.05):.2f} 円  ← 0.5 円の端数")
    print(f"1,010 円 × 1 冊 × 10% 引き: {1010 * 1 * (1 - 0.10):.2f} 円")
    print(f"値引き率の種類            : {sorted(valid['discount_rate'].unique().tolist())}")


if __name__ == "__main__":
    main()
