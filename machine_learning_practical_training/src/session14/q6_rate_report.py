"""問題6 の解答：率のレポートを作り、ドメイン知識のフラグが効くかどうかを検証する。

使い方:
    docker compose exec lab python src/session14/q6_rate_report.py
"""

from __future__ import annotations

import pandas as pd

from common import (
    BIG_DISCOUNT_RATE,
    NEW_CUSTOMER_DAYS,
    WEEKDAY_JA,
    add_all_features,
    cancel_rate,
    evaluate,
    load_order_table,
)

# ② と ⑤ は増分実験と同じ列の組み合わせにする（そうしないと他の段階と比べられない）
BASE_NUMERIC = ["unit_price", "quantity", "discount_rate", "days_since_signup"]
STEP5_NUMERIC = BASE_NUMERIC + [
    "amount", "age", "weekday", "month", "is_weekend",
    "is_new_customer", "is_big_discount",
]


def rate_report(df: pd.DataFrame) -> dict:
    """キャンセル率をグループ別に集めて辞書で返す。"""
    is_new = df["days_since_signup"] < NEW_CUSTOMER_DAYS
    is_big = df["discount_rate"] >= BIG_DISCOUNT_RATE
    by_channel = df.groupby("channel")["is_canceled"].mean().sort_values(ascending=False)
    by_weekday = df.groupby(df["ordered_at"].dt.dayofweek)["is_canceled"].mean()
    return {
        "overall": cancel_rate(df),
        "by_channel": {str(k): float(v) for k, v in by_channel.items()},
        "min_channel_count": int(df["channel"].value_counts().min()),
        "new": cancel_rate(df, is_new),
        "not_new": cancel_rate(df, ~is_new),
        "big_discount": cancel_rate(df, is_big),
        "weekday_min": float(by_weekday.min()),
        "weekday_max": float(by_weekday.max()),
        "weekday_rates": {WEEKDAY_JA[int(k)]: float(v) for k, v in by_weekday.items()},
    }


def main() -> None:
    df = add_all_features(load_order_table())
    report = rate_report(df)

    print(f"■ キャンセル率のレポート（母集団 {len(df):,} 行）")
    print(f"全体 : {report['overall']:.2%}")
    for channel, rate in report["by_channel"].items():
        print(f"流入経路 {channel} : {rate:.2%}")
    # 件数の内訳は df["channel"].value_counts() で見られる。ここでは大きさだけ確かめる
    print(f"流入経路のどのグループも 5,000 件を超えているか : {report['min_channel_count'] > 5000}")
    print(f"登録 {NEW_CUSTOMER_DAYS} 日未満（0〜6 日） : {report['new']:.2%} / それ以外 : {report['not_new']:.2%}")
    print(f"倍率 : {report['new'] / report['not_new']:.1f} 倍")
    print(f"値引き {BIG_DISCOUNT_RATE:.0%} 以上 : {report['big_discount']:.2%}")
    print(f"曜日別 : 最小 {report['weekday_min']:.2%} / 最大 {report['weekday_max']:.2%}")

    print("\n■ フラグを足す前と後（増分実験の ② と ⑤ と同じ組み合わせ）")
    base = evaluate(df, BASE_NUMERIC, ["channel"])
    with_flags = evaluate(df, STEP5_NUMERIC, ["channel"])
    print(f"② {base['n_features']} 列 : ROC AUC {base['roc_auc']:.4f} / PR-AUC {base['pr_auc']:.4f}")
    print(f"⑤ {with_flags['n_features']} 列 : ROC AUC {with_flags['roc_auc']:.4f} / PR-AUC {with_flags['pr_auc']:.4f}")
    print(f"ROC AUC が改善したか : {with_flags['roc_auc'] > base['roc_auc']}")

    print("\n■ 率に差があるのに、フラグを足しても改善しない理由")
    print("1. 決定木は days_since_signup を自分で 7 日あたりで分割できるので、同じ情報を 2 回渡している")
    print("2. discount_rate も同じ。0.20 以上という境目はモデルが自分で見つけられる")
    print("3. 列が増えるほど分割の候補が増え、訓練データだけに合う分割を選ぶ余地も増える")
    print("→ ドメイン知識は「率を見て、どの列を持ち込むか決める」段階でいちばん効きます")


if __name__ == "__main__":
    main()
