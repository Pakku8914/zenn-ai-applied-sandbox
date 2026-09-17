"""問題3 の解答：金額と年齢を作って基準モデルに足し、効果を測る。

使い方:
    docker compose exec lab python src/session14/q3_ratio_features.py
"""

from __future__ import annotations

import pandas as pd

from common import evaluate, load_order_table

BASE_NUMERIC = ["unit_price", "quantity", "discount_rate", "days_since_signup"]


def add_amount_and_age_by_hand(df: pd.DataFrame) -> pd.DataFrame:
    """売上額と年齢を足す。行ごとに丸めないのが本書の売上規約。"""
    out = df.copy()
    out["amount"] = out["unit_price"] * out["quantity"] * (1 - out["discount_rate"])
    out["age"] = 2026 - out["birth_year"]  # 基準日を固定しているので毎年変わらない
    return out


def compare_base_and_step3(df: pd.DataFrame) -> tuple[dict, dict]:
    """②（5 列）と ③（7 列）を同じ条件で評価して返す。"""
    base = evaluate(df, BASE_NUMERIC, ["channel"])
    step3 = evaluate(df, BASE_NUMERIC + ["amount", "age"], ["channel"])
    return base, step3


def main() -> None:
    df = add_amount_and_age_by_hand(load_order_table())

    # 1. amount の検算（有効注文だけを合計する。合計してから丸める）
    valid = df.loc[df["is_canceled"] == 0, "amount"]
    print(f"有効注文 : {len(valid):,} 件")
    print(f"売上合計 : {round(float(valid.sum())):,} 円")

    # 2. age の作り方の確認（どちらも同じ引き算で作れているか）
    same = bool((df["age"] == 2026 - df["birth_year"]).all())
    print(f"age が 2026 − birth_year になっているか : {same}")

    # 3. 基準モデルに足して効果を測る
    base, step3 = compare_base_and_step3(df)
    print("\n■ 金額と年齢を足す前と後（分割条件は同じ）")
    print(f"② {base['n_features']} 列 : ROC AUC {base['roc_auc']:.4f} / PR-AUC {base['pr_auc']:.4f}")
    print(f"③ {step3['n_features']} 列 : ROC AUC {step3['roc_auc']:.4f} / PR-AUC {step3['pr_auc']:.4f}")
    print(f"ROC AUC が改善したか : {step3['roc_auc'] > base['roc_auc']}")
    print(f"PR-AUC が改善したか : {step3['pr_auc'] > base['pr_auc']}")

    print("\n■ 判断")
    print("amount は unit_price・quantity・discount_rate の掛け算なので、新しい情報はありません。")
    print("age は顧客マスタから持ち込んだ列ですが、キャンセルの起こりやすさと関係がありません。")
    print("結果として列が 2 本増えただけになり、指標はわずかに下がりました。")


if __name__ == "__main__":
    main()
