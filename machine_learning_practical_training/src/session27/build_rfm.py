"""顧客 1 人 1 行の表（RFM 風の 3 指標）を作り、母集団を確認する。

使い方:
    docker compose exec lab python src/session27/build_rfm.py
"""

from __future__ import annotations

from common import ACTIVE_DAYS, FEATURE_JA, FEATURES, count_customers, load_valid_orders, rfm_table


def summary() -> dict:
    """この章の母集団と 3 指標の平均をまとめて返す（verify から参照する）。"""
    orders = load_valid_orders()
    table = rfm_table()
    counts = count_customers()
    return {
        "valid_orders": len(orders),
        "revenue": round(float(orders["amount"].sum())),  # 合計してから整数にする（本書の規約）
        "customers": counts,
        "n_rows": len(table),
        "columns": list(table.columns),
        "dtypes": [str(dtype) for dtype in table.dtypes],
        "means": {name: float(table[name].mean()) for name in FEATURES},
        "frequency_sum": int(table["frequency"].sum()),
        "monetary_sum": round(float(table["monetary"].sum())),
        "active_le": int((table["recency"] <= ACTIVE_DAYS).sum()),
        "active_lt": int((table["recency"] < ACTIVE_DAYS).sum()),
        "min_frequency": int(table["frequency"].min()),
    }


def main() -> None:
    info = summary()

    print("■ 1. 母集団（有効注文だけを使う）")
    print(f"有効注文の件数 : {info['valid_orders']:,} 件（完全重複 30 件とキャンセルを除いた行）")
    print(f"売上合計       : {info['revenue']:,} 円")
    print("顧客数の 3 通りの数え方")
    print(f"  ① 全顧客                     : {info['customers']['all']:,} 人")
    print(f"  ② 注文が 1 件以上ある顧客     : {info['customers']['ordered']:,} 人")
    print(f"  ③ 有効注文が 1 件以上ある顧客 : {info['customers']['valid']:,} 人  ← この章で使う母集団")

    print("\n■ 2. できあがった表の形（顧客 1 人 1 行）")
    print(f"行数 : {info['n_rows']:,} 行（③ と一致する）")
    for name, dtype in zip(info["columns"], info["dtypes"]):
        print(f"  {name:<10}{dtype:<10}{FEATURE_JA[name]}")

    print("\n■ 3. 3 指標の平均")
    print(f"recency   : {info['means']['recency']:>8,.0f} 日")
    print(f"frequency : {info['means']['frequency']:>8.1f} 回")
    print(f"monetary  : {info['means']['monetary']:>8,.0f} 円")
    print(f"frequency の合計 : {info['frequency_sum']:,} 回（有効注文の件数と一致する）")
    print(f"monetary の合計  : {info['monetary_sum']:,} 円（売上合計と一致する）")
    print(f"frequency の最小 : {info['min_frequency']} 回（有効注文が 0 回の人はこの表にいない）")

    print(f"\n■ 4. アクティブ顧客（recency が {ACTIVE_DAYS} 日以内）")
    print(f"{info['active_le']:,} 人 / {info['n_rows']:,} 人（セッション6 で数えたアクティブ顧客と同じ集団）")

    print("\n■ 5. この章では train_test_split をしない")
    print("教師あり学習では『未知データで当たるか』を測るために分割しました。")
    print("教師なし学習には正解の列がないので、当たり外れを測る相手がいません。")
    print("分割する代わりに、①指標が妥当か ②結果が安定しているか ③業務で使えるか を確かめます。")


if __name__ == "__main__":
    main()
