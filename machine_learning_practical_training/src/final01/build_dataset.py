"""課題1: 期間を切って特徴量と目的変数を作る。

このプロジェクトで唯一「やり直しのきかない」工程です。ここで cutoff より後の情報が
1 つでも混ざると、以降のすべての数値が信用できなくなります。

使い方:
    docker compose exec lab python src/final01/build_dataset.py
"""

from __future__ import annotations

from common import (
    AS_OF,
    CATEGORICAL,
    CUTOFF,
    FEATURES,
    HORIZON_DAYS,
    LABEL_START,
    NUMERIC,
    TARGET,
    dataset,
    valid_orders,
)


def summary() -> dict:
    """母集団・目的変数・特徴量の形を 1 か所で数える。"""
    data = dataset()
    df = data["df"]
    valid = valid_orders()
    past = valid.loc[valid["ordered_at"] <= CUTOFF]
    all_customers = int(valid["customer_id"].nunique())
    return {
        "cutoff": str(CUTOFF.date()),
        "label_start": str(LABEL_START.date()),
        "as_of": str(AS_OF.date()),
        "horizon_days": HORIZON_DAYS,
        "n_valid_orders": int(len(valid)),
        "n_past_orders": int(len(past)),
        "all_customers": all_customers,
        "n_customers": data["n_customers"],
        "dropped": all_customers - data["n_customers"],
        "n_positive": data["n_positive"],
        "n_negative": data["n_customers"] - data["n_positive"],
        "positive_rate": data["positive_rate"],
        "n_features": len(FEATURES),
        "n_numeric": len(NUMERIC),
        "n_categorical": len(CATEGORICAL),
        "n_train": data["n_train"],
        "n_test": data["n_test"],
        "n_positive_test": data["n_positive_test"],
        "n_negative_test": data["n_test"] - data["n_positive_test"],
        "positive_rate_test": data["positive_rate_test"],
        # 「未来を混ぜていないこと」を毎回機械で確かめる
        "past_max_date": str(past["ordered_at"].max().date()),
        "past_within_cutoff": bool(past["ordered_at"].max() <= CUTOFF),
        "numeric_has_no_nan": int(df[NUMERIC].isna().sum().sum()) == 0,
        "target_is_binary": sorted(df[TARGET].unique().tolist()) == [0, 1],
    }


def main() -> None:
    info = summary()

    print("■ 1. 期間の切り方")
    print(f"観測期間: 〜 {info['cutoff']}（ここまでの履歴だけで特徴量を作る）")
    print(f"予測期間: {info['label_start']} 〜 {info['as_of']}（{info['horizon_days']} 日間・ここから目的変数だけを作る）")
    print(f"観測期間の注文がすべて cutoff 以内に収まっている: {info['past_within_cutoff']}")
    print()

    print("■ 2. 対象顧客")
    print(f"有効注文がある顧客（全期間）: {info['all_customers']:,} 人")
    print(f"cutoff までに有効注文がある顧客: {info['n_customers']:,} 人")
    print(f"→ cutoff で切ることで対象から外れた顧客: {info['dropped']:,} 人")
    print()

    print("■ 3. 目的変数（その後 90 日以内に再購入したか）")
    print(f"再購入あり: {info['n_positive']:,} 人 / 再購入なし: {info['n_negative']:,} 人")
    print(f"正例率: {info['positive_rate']:.4f}")
    print()

    print("■ 4. 特徴量と分割")
    print(f"特徴量: 数値 {info['n_numeric']} 列 + カテゴリ {info['n_categorical']} 列 = {info['n_features']} 列")
    print(f"訓練 {info['n_train']:,} 件 / 評価 {info['n_test']:,} 件")
    print(f"評価データの正例 {info['n_positive_test']:,} 人 / 負例 {info['n_negative_test']:,} 人（正例率 {info['positive_rate_test']:.4f}）")
    print()

    print("■ 5. 作った表の点検")
    print(f"数値列に欠損がない: {info['numeric_has_no_nan']}")
    print(f"目的変数が 0 と 1 だけ: {info['target_is_binary']}")
    print("判断: この 3 つの期間（観測・予測・基準日）を混ぜない限り、")
    print("      ここから先の数値は『本番でも手に入る情報だけ』で作られています。")


if __name__ == "__main__":
    main()
