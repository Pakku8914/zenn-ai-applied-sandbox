"""問題3 の解答: 顧客の重なりを数え、グループ分割と層化分割を比べる。

実行:
    docker compose exec lab python src/session22/q3_group_split.py
"""

from __future__ import annotations

from common import (
    cv_auc,
    features_target,
    group_cv,
    load_review_table,
    stratified_cv,
    summarize,
)


def customer_facts(df) -> dict[str, int]:
    """同じ顧客が何件レビューを書いているかを数える。"""
    counts = df["customer_id"].value_counts()
    return {
        "reviews": len(df),
        "customers": int(counts.size),
        "max_per_customer": int(counts.max()),
        "repeat_customers": int((counts >= 2).sum()),
    }


def shared_customers(df, cv, groups=None) -> list[int]:
    """fold ごとに「訓練データと評価データの両方に現れた顧客」の人数を数える。"""
    X, y = features_target(df)
    customer = df["customer_id"].to_numpy()
    shared = []
    for train_index, test_index in cv.split(X, y, groups):
        shared.append(len(set(customer[train_index]) & set(customer[test_index])))
    return shared


def analyze(df) -> dict[str, object]:
    """グループ分割と層化分割を、スコアと顧客の重なりの両面で比べる。"""
    groups = df["customer_id"]
    group_mean, group_std = summarize(cv_auc(df, group_cv(), groups=groups))
    strat_mean, strat_std = summarize(cv_auc(df, stratified_cv()))
    group_shared = shared_customers(df, group_cv(), groups)
    strat_shared = shared_customers(df, stratified_cv())
    return {
        **customer_facts(df),
        "group_mean": group_mean,
        "group_std": group_std,
        "strat_mean": strat_mean,
        "strat_std": strat_std,
        "gap": group_mean - strat_mean,
        "group_shared": group_shared,
        "strat_shared": strat_shared,
        "group_is_clean": all(count == 0 for count in group_shared),
        "strat_has_overlap": any(count > 0 for count in strat_shared),
        "gap_is_small": bool(abs(group_mean - strat_mean) < 0.005),
    }


def main() -> None:
    result = analyze(load_review_table())

    print("■ 1. 顧客の重なり")
    print(f"顧客 {result['customers']} 人 / レビュー {result['reviews']} 件 / 1 顧客あたり最大 {result['max_per_customer']} 件")
    print(f"2 件以上書いた顧客: {result['repeat_customers']} 人")
    print()

    print("■ 2. fold をまたいで現れた顧客の人数")
    print(f"グループ分割 : {result['group_shared']}")
    print(f"層化分割     : {result['strat_shared']}")
    print(f"グループ分割では 1 人も重なっていないか: {result['group_is_clean']}")
    print(f"層化分割では重なっているか            : {result['strat_has_overlap']}")
    print()

    print("■ 3. ROC AUC の比較")
    print(f"グループ分割 : 平均 {result['group_mean']:.4f} / 標準偏差 {result['group_std']:.4f}")
    print(f"層化分割     : 平均 {result['strat_mean']:.4f} / 標準偏差 {result['strat_std']:.4f}")
    print(f"差            : {result['gap']:+.4f}")
    print(f"差は許容誤差 0.005 より小さいか: {result['gap_is_small']}")
    print()

    print("■ 4. 説明例")
    print("顧客が訓練と評価にまたがっていても、このモデルは顧客の情報を一切使っていません。")
    print("特徴量は本の単価・ページ数・刊行年・本文の長さ・カテゴリだけなので、")
    print("「同じ人をもう一度見た」ことが有利にならず、グループ分割にしても数値が動きません。")
    print("顧客ごとの平均星などを特徴量に入れた瞬間に、この確認は必須になります。")


if __name__ == "__main__":
    main()
