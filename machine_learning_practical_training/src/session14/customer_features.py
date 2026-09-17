"""顧客単位の集約特徴量を「その注文より前」だけで作る（未来を混ぜない）。

使い方:
    docker compose exec lab python src/session14/customer_features.py
"""

from __future__ import annotations

import pandas as pd

from common import add_leak_feature, add_past_features, evaluate, load_order_table


def make_toy() -> pd.DataFrame:
    """2 人の顧客・5 件の注文だけの練習用データ。手で数えて答え合わせできる大きさにする。"""
    return pd.DataFrame(
        {
            "order_id": ["T1", "T2", "T3", "T4", "T5"],
            "customer_id": ["C1", "C1", "C1", "C2", "C2"],
            "ordered_at": pd.to_datetime(
                ["2026-01-05", "2026-02-10", "2026-03-01", "2026-01-20", "2026-04-02"]
            ),
            "is_canceled": [0, 1, 0, 1, 0],
        }
    )


def main() -> None:
    # 1. 練習用データで、過去だけの集計と全期間の集計の違いを目で確かめる
    toy = add_leak_feature(add_past_features(make_toy()))
    print("■ 練習用データ 5 件（C1 は 3 回・C2 は 2 回買っている）")
    for row in toy.itertuples():
        print(
            f"{row.order_id} {row.ordered_at:%Y-%m-%d} {row.customer_id} "
            f"is_canceled={row.is_canceled} past_orders={row.past_orders} "
            f"past_cancels={row.past_cancels:.0f} all_time_cancels={row.all_time_cancels}"
        )
    print("→ T1 の all_time_cancels は 1。まだ 1 件もキャンセルされていない時点なのに、未来を知っている")

    # 2. 実データで作る
    df = load_order_table()
    past = add_leak_feature(add_past_features(df))
    print("\n■ 実データ（60,031 行）で作った集約特徴量")
    print(f"元の表と同じ並び順に戻っているか : {past['order_id'].equals(df['order_id'])}")
    print(f"past_orders の平均 : {past['past_orders'].mean():.2f}")
    print(f"past_orders の最大 : {int(past['past_orders'].max())}")
    print(f"past_orders が 0（その顧客の 1 件目）の行 : {int((past['past_orders'] == 0).sum()):,} 件")
    print(f"all_time_cancels の平均 : {past['all_time_cancels'].mean():.3f}")
    print(f"past_cancels が all_time_cancels を超えない行の割合 : {(past['past_cancels'] <= past['all_time_cancels']).mean():.0%}")

    # 3. 全期間の集計は「答え」を含んでいる。0 なら必ずキャンセルされていない
    zero_leak = past["all_time_cancels"] == 0
    print(f"all_time_cancels が 0 の行のキャンセル率 : {past.loc[zero_leak, 'is_canceled'].mean():.2%}")
    print("→ この列が 0 の行は、見ただけで「キャンセルされていない」と分かってしまう")

    # 4. 並べ替えたまま学習すると、同じ random_state でも別の分割になる
    numeric = ["unit_price", "quantity", "discount_rate", "days_since_signup"]
    restored = evaluate(past, numeric, ["channel"])
    shuffled = evaluate(past.sort_values("ordered_at"), numeric, ["channel"])
    print("\n■ 並び順を戻したかどうかで結果が変わる（特徴量は同じ 5 列）")
    print(f"元の並び順（正しい） : ROC AUC {restored['roc_auc']:.4f}")
    print(f"時間順のまま学習     : ROC AUC {shuffled['roc_auc']:.4f}")
    print("→ 数字は上がるが、モデルが良くなったのではなく分割が変わっただけ")


if __name__ == "__main__":
    main()
