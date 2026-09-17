"""問題3: region の欠損を削除・定数・最頻値で処理し、影響を並べて比べる。

使い方:
    docker compose exec lab python src/session11/q3_compare_strategies.py
"""

from __future__ import annotations

from common import MISSING_LABEL, REGIONS, load_customers, load_orders, region_missing_revenue


def main() -> None:
    customers = load_customers()
    orders = load_orders()
    mode_value = customers["region"].mode().iloc[0]  # 埋める値はデータから計算する

    deleted = customers.dropna(subset=["region"])
    constant = customers.assign(region=customers["region"].fillna(MISSING_LABEL))
    filled = customers.assign(region=customers["region"].fillna(mode_value))

    print(f"■ 3 方針の比較（最頻値は {mode_value}）")
    for label, df in [("削除", deleted), (f"定数（{MISSING_LABEL}）", constant), ("最頻値", filled)]:
        share = float((df["region"] == mode_value).mean())
        print(f"  {label}: {len(df):,} 行 / カテゴリ {df['region'].nunique()}"
              f" / {mode_value} {share:.2%}")

    print(f"■ 削除で失う売上: {round(region_missing_revenue(customers, orders)):,} 円")
    print(f"■ 「{MISSING_LABEL}」の人数: {int((constant['region'] == MISSING_LABEL).sum()):,} 人")

    counts = filled["region"].value_counts().reindex(REGIONS)
    print("■ 最頻値代入後の分布: " + " / ".join(f"{name} {int(value):,}" for name, value in counts.items()))
    print(f"■ 検算: 分布の合計 {int(counts.sum()):,} = 元の行数 {len(customers):,}"
          f" → {int(counts.sum()) == len(customers)}")


if __name__ == "__main__":
    main()
