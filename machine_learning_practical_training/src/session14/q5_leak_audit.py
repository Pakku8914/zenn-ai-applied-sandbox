"""問題5 の解答：跳ね上がった精度の正体を突き止める（データリークの監査）。

使い方:
    docker compose exec lab python src/session14/q5_leak_audit.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from common import add_all_features, evaluate, load_order_table, split_xy

NUMERIC_PAST = [
    "unit_price", "quantity", "discount_rate", "days_since_signup",
    "amount", "age", "weekday", "month", "is_weekend",
    "is_new_customer", "is_big_discount", "past_orders", "past_cancels",
]

CHECKLIST = [
    "その特徴量は、予測したい時点で本当に手に入るか（未来の値を使っていないか）",
    "集計に使った期間は、予測したい時点より前だけで切られているか",
    "目的変数そのもの・目的変数から計算した値が混ざっていないか",
    "本番で同じ手順を再現できるか（その場でしか作れない列になっていないか）",
]


def audit(df: pd.DataFrame) -> dict:
    """リークの証拠と、当て推量の指標を集める（モデルの学習はしない）。"""
    zero = df["all_time_cancels"] == 0
    _, _, _, y_test = split_xy(df, NUMERIC_PAST, ["channel"])
    flat = np.full(len(y_test), 0.5)  # 全員に同じ確率を出す＝何も学習していないモデル
    others = df["all_time_cancels"] - df["is_canceled"]  # 自分以外のキャンセル数
    return {
        "zero_rows_cancel_rate": float(df.loc[zero, "is_canceled"].mean()),
        "self_included": bool((df["all_time_cancels"] >= df["is_canceled"]).all()),
        "others_ge_past": bool((others >= df["past_cancels"]).all()),
        "chance_roc_auc": float(roc_auc_score(y_test, flat)),
        "chance_pr_auc": float(average_precision_score(y_test, flat)),
        "test_positive_rate": float(y_test.mean()),
    }


def main() -> None:
    df = add_all_features(load_order_table())
    facts = audit(df)

    print("■ 当て推量（全員に同じ確率を出す）の指標")
    print(f"ROC AUC : {facts['chance_roc_auc']:.4f}")
    print(f"PR-AUC  : {facts['chance_pr_auc']:.4f}")
    print(f"評価データの正例率 : {facts['test_positive_rate']:.2%}")

    print("\n■ 過去だけの集計（⑥）と全期間の集計（⑦）")
    past_only = evaluate(df, NUMERIC_PAST, ["channel"])
    leaked = evaluate(df, NUMERIC_PAST + ["all_time_cancels"], ["channel"])
    print(f"⑥ : ROC AUC {past_only['roc_auc']:.4f} / PR-AUC {past_only['pr_auc']:.4f}")
    print(f"⑦ : ROC AUC {leaked['roc_auc']:.4f} / PR-AUC {leaked['pr_auc']:.4f}")
    print(f"ROC AUC の差が 0.10 ポイントを超えたか : {leaked['roc_auc'] - past_only['roc_auc'] > 0.10}")

    print("\n■ リークの証拠")
    print(f"all_time_cancels が 0 の行のキャンセル率 : {facts['zero_rows_cancel_rate']:.2%}")
    print(f"all_time_cancels はその行の is_canceled を必ず含むか : {facts['self_included']}")
    print(f"自分以外のキャンセル数が past_cancels 以上になるか : {facts['others_ge_past']}")
    print("→ 自分の分を引いても、未来の注文のキャンセルが残るので依然としてリークです")

    print("\n■ 精度が跳ねたときのチェックリスト")
    for i, item in enumerate(CHECKLIST, start=1):
        print(f"{i}. {item}")


if __name__ == "__main__":
    main()
