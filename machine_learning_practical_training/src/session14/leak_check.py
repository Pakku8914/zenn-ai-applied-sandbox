"""精度が跳ねたときに疑う手順。全期間の集計はデータリークだと確かめる。

使い方:
    docker compose exec lab python src/session14/leak_check.py
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

from common import add_all_features, evaluate, load_order_table, split_xy

NUMERIC_PAST = [
    "unit_price", "quantity", "discount_rate", "days_since_signup",
    "amount", "age", "weekday", "month", "is_weekend",
    "is_new_customer", "is_big_discount", "past_orders", "past_cancels",
]


def main() -> None:
    df = add_all_features(load_order_table())

    # 1. 何も学習していないモデル（全員に同じ確率を出す）の指標を先に測る
    _, _, _, y_test = split_xy(df, NUMERIC_PAST, ["channel"])
    flat = np.full(len(y_test), 0.5)
    print("■ 当て推量（全員に同じ確率 0.5 を出す）の指標")
    print(f"ROC AUC : {roc_auc_score(y_test, flat):.4f}")
    print(f"PR-AUC  : {average_precision_score(y_test, flat):.4f}（評価データの正例率と同じ）")

    # 2. 過去だけの集計（⑥）と、全期間の集計を足した場合（⑦）を比べる
    past_only = evaluate(df, NUMERIC_PAST, ["channel"])
    leaked = evaluate(df, NUMERIC_PAST + ["all_time_cancels"], ["channel"])
    print("\n■ 過去だけの集計と、全期間の集計の違い")
    print(f"⑥ 過去だけ : ROC AUC {past_only['roc_auc']:.4f} / PR-AUC {past_only['pr_auc']:.4f}")
    print(f"⑦ 全期間   : ROC AUC {leaked['roc_auc']:.4f} / PR-AUC {leaked['pr_auc']:.4f}")
    print(f"ROC AUC の差が 0.10 ポイントを超えたか : {leaked['roc_auc'] - past_only['roc_auc'] > 0.10}")

    # 3. 跳ねた原因を突き止める。この列が 0 なら答えが決まってしまう
    zero = df["all_time_cancels"] == 0
    print("\n■ 跳ねた特徴量の中身を確かめる")
    print(f"all_time_cancels が 0 の行のキャンセル率 : {df.loc[zero, 'is_canceled'].mean():.2%}")
    print("→ 0 か 0 でないかを見るだけで、答えの一部が分かってしまう（= その行の答えを足し込んでいる）")

    print("\n■ 精度が跳ねたときのチェックリスト")
    for i, item in enumerate(
        [
            "その特徴量は、予測したい時点で本当に手に入るか（未来の値を使っていないか）",
            "集計に使った期間は、予測したい時点より前だけで切られているか",
            "目的変数そのもの・目的変数から計算した値が混ざっていないか",
            "本番で同じ手順を再現できるか（その場でしか作れない列になっていないか）",
        ],
        start=1,
    ):
        print(f"{i}. {item}")


if __name__ == "__main__":
    main()
