"""比率・差分・交互作用の作り方を確かめ、金額と年齢を足したモデルを基準と比べる。

使い方:
    docker compose exec lab python src/session14/ratio_features.py
"""

from __future__ import annotations

import pandas as pd

from common import add_amount_and_age, add_domain_flags, evaluate, load_order_table


def make_toy() -> pd.DataFrame:
    """作り方を目で確かめるための 4 行の練習用データ。"""
    return pd.DataFrame(
        {
            "order_id": ["T1", "T2", "T3", "T4"],
            "unit_price": [1000, 1000, 4000, 4000],
            "quantity": [1, 3, 1, 2],
            "discount_rate": [0.00, 0.20, 0.20, 0.05],
            "days_since_signup": [0, 100, 3, 500],
            "birth_year": [1990, 1990, 2000, 1960],
        }
    )


def add_designed_features(df: pd.DataFrame) -> pd.DataFrame:
    """既にある列を組み合わせて、比率・差分・交互作用の 3 つの型を作る。"""
    out = add_domain_flags(add_amount_and_age(df))
    out["net_unit_price"] = out["unit_price"] * (1 - out["discount_rate"])   # 比率を当てた実質単価
    out["discount_amount"] = out["unit_price"] * out["quantity"] * out["discount_rate"]  # 差分（値引き額）
    out["new_and_big_discount"] = out["is_new_customer"] * out["is_big_discount"]  # 交互作用（両方成立）
    return out


def main() -> None:
    # 1. 練習用データで、それぞれの列がどう計算されるかを確かめる
    toy = add_designed_features(make_toy())
    print("■ 練習用データ 4 件")
    for row in toy.itertuples():
        print(
            f"{row.order_id} amount={row.amount:.0f} 実質単価={row.net_unit_price:.0f} "
            f"値引き額={row.discount_amount:.0f} age={row.age} "
            f"新規={row.is_new_customer} 大値引き={row.is_big_discount} "
            f"交互作用={row.new_and_big_discount}"
        )
    print("→ 交互作用は「新規かつ大きな値引き」のときだけ 1 になる（T3 だけ）")

    # 2. 実データ。amount が売上規約どおりに計算できているかを合計で確かめる
    df = add_designed_features(load_order_table())
    valid_amount = df.loc[df["is_canceled"] == 0, "amount"]
    print("\n■ 実データでの確認")
    print(f"有効注文 : {len(valid_amount):,} 件 / 売上合計 : {round(float(valid_amount.sum())):,} 円")

    # 3. 基準モデル（②）に amount と age を足す（③）と、指標はどうなるか
    numeric = ["unit_price", "quantity", "discount_rate", "days_since_signup"]
    base = evaluate(df, numeric, ["channel"])
    added = evaluate(df, numeric + ["amount", "age"], ["channel"])
    print("\n■ 金額と年齢を足す前と後")
    print(f"② 5 列 : ROC AUC {base['roc_auc']:.4f} / PR-AUC {base['pr_auc']:.4f}")
    print(f"③ 7 列 : ROC AUC {added['roc_auc']:.4f} / PR-AUC {added['pr_auc']:.4f}")
    print(f"改善したか : {added['roc_auc'] > base['roc_auc']}")
    print("→ amount は unit_price・quantity・discount_rate の掛け算。元の 3 列がすでに入っている")


if __name__ == "__main__":
    main()
