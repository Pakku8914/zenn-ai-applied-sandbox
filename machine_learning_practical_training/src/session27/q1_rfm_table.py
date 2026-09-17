"""問題1: 有効注文のある 7,629 人について RFM 風の 3 指標を作る。

使い方:
    docker compose exec lab python src/session27/q1_rfm_table.py
"""

from __future__ import annotations

import pandas as pd

from common import ACTIVE_DAYS, DATA_DIR, FEATURES, ID_COLUMNS, REFERENCE_DATE, count_customers, rfm_table


def build() -> pd.DataFrame:
    """3 指標の表を「読み込みから」自分で組み立てる（common に頼らずに書いてみる）。"""
    orders = pd.read_csv(DATA_DIR / "orders.csv", parse_dates=["ordered_at"], dtype=ID_COLUMNS)
    deduped = orders.drop_duplicates()                     # 完全重複 30 件を落とす
    valid = deduped[deduped["is_canceled"] == 0]           # キャンセルを除く
    valid = valid.assign(amount=valid["unit_price"] * valid["quantity"] * (1 - valid["discount_rate"]))
    table = valid.groupby("customer_id").agg(
        last_order=("ordered_at", "max"),
        frequency=("order_id", "count"),
        monetary=("amount", "sum"),
    )
    table["recency"] = (REFERENCE_DATE - table["last_order"]).dt.days
    return table[FEATURES].astype({"recency": "int64", "frequency": "int64", "monetary": "float64"})


def analyze() -> dict:
    """自分で組み立てた表が、common.rfm_table() と一致することまで確かめる。"""
    table = build()
    counts = count_customers()
    return {
        "customers": counts,
        "n_rows": len(table),
        "matches_common": bool(table.equals(rfm_table())),
        "means": {name: float(table[name].mean()) for name in FEATURES},
        "frequency_sum": int(table["frequency"].sum()),
        "revenue": round(float(table["monetary"].sum())),
        "active": int((table["recency"] <= ACTIVE_DAYS).sum()),
        "no_missing": bool(table.notna().to_numpy().all()),
    }


def main() -> None:
    info = analyze()

    print("■ 1. 顧客数の 3 通りの数え方")
    print(f"  ① 全顧客                     : {info['customers']['all']:,} 人")
    print(f"  ② 注文が 1 件以上ある顧客     : {info['customers']['ordered']:,} 人")
    print(f"  ③ 有効注文が 1 件以上ある顧客 : {info['customers']['valid']:,} 人  ← 使うのはこれ")

    print("\n■ 2. できあがった表")
    print(f"行数 : {info['n_rows']:,} 行（③ と一致）")
    print(f"欠損が 1 つもないか : {info['no_missing']}")
    print(f"common.rfm_table() と一致するか : {info['matches_common']}")

    print("\n■ 3. 3 指標の平均")
    print(f"  recency   : {info['means']['recency']:>8,.0f} 日")
    print(f"  frequency : {info['means']['frequency']:>8.1f} 回")
    print(f"  monetary  : {info['means']['monetary']:>8,.0f} 円")

    print("\n■ 4. 合計で答え合わせ")
    print(f"frequency の合計 : {info['frequency_sum']:,} 回（有効注文の件数）")
    print(f"monetary の合計  : {info['revenue']:,} 円（本書の売上合計）")
    print(f"アクティブ顧客（recency {ACTIVE_DAYS} 日以内） : {info['active']:,} 人")

    print("\n■ 5. 3 通りの数え方の使い分け")
    print("売上や購買行動を語るときは ③ を使います。① を分母にすると比率が小さく出ます。")
    print("『注文がない 346 人』と『キャンセルだけの 25 人』を混ぜると、平均が実態から外れます。")


if __name__ == "__main__":
    main()
