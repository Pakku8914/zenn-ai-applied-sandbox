"""問題4 の解答：特徴量を 1 段階ずつ足して、同じ条件で比べる（増分実験）。

使い方:
    docker compose exec lab python src/session14/q4_feature_steps.py
"""

from __future__ import annotations

import pandas as pd

from common import add_all_features, evaluate, load_order_table

# 各段階で使う特徴量を、前の段階を壊さずに積み上げて書く
NUM1 = ["unit_price", "quantity", "discount_rate"]
NUM2 = NUM1 + ["days_since_signup"]
NUM3 = NUM2 + ["amount", "age"]
NUM4 = NUM3 + ["weekday", "month", "is_weekend"]
NUM5 = NUM4 + ["is_new_customer", "is_big_discount"]
NUM6 = NUM5 + ["past_orders", "past_cancels"]
NUM7 = NUM6 + ["all_time_cancels"]

STEPS: list[tuple[str, list[str], list[str]]] = [
    ("① 素の 3 列", NUM1, []),
    ("② + 経過日数と流入経路（基準）", NUM2, ["channel"]),
    ("③ + 金額と年齢", NUM3, ["channel"]),
    ("④ + 日時（曜日・月・週末）", NUM4, ["channel"]),
    ("⑤ + ドメイン知識のフラグ", NUM5, ["channel"]),
    ("⑥ + 過去だけの集計", NUM6, ["channel"]),
    ("⑦ + 全期間のキャンセル数（リーク）", NUM7, ["channel"]),
]


def run_all_steps(df: pd.DataFrame) -> list[dict]:
    """段階ごとに学習し、列数・ROC AUC・PR-AUC を集める。"""
    results = []
    for label, numeric, categorical in STEPS:
        score = evaluate(df, numeric, categorical)
        results.append({"label": label, **score})
    return results


def main() -> None:
    df = add_all_features(load_order_table())
    results = run_all_steps(df)

    print("■ 段階ごとの結果")
    for r in results:
        print(f"{r['label']} : {r['n_features']} 列 / ROC AUC {r['roc_auc']:.4f} / PR-AUC {r['pr_auc']:.4f}")

    base = results[1]
    print("\n■ 基準モデル（②）と比べる")
    for r in results[2:6]:
        print(f"{r['label']} : ROC AUC {'改善' if r['roc_auc'] > base['roc_auc'] else '改善せず'}"
              f" / PR-AUC {'改善' if r['pr_auc'] > base['pr_auc'] else '改善せず'}")
    print(f"⑦ だけ ROC AUC が 0.10 ポイント以上上がったか : {results[6]['roc_auc'] - base['roc_auc'] > 0.10}")

    print("\n■ 判断")
    print("①→② で大きく上がったのは、顧客マスタから新しい情報（流入経路・登録からの日数）を")
    print("持ち込んだからです。③〜⑥ は既にある情報の作り直し、または予測に関係のない情報なので、")
    print("列が増えても指標は改善しません。⑦ の跳ね上がりはデータリークによるものです。")


if __name__ == "__main__":
    main()
