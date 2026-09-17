"""問題2 の解答：その注文より前だけを集計した特徴量を作る。

使い方:
    docker compose exec lab python src/session14/q2_past_features.py
"""

from __future__ import annotations

import pandas as pd

from common import load_order_table


def make_toy() -> pd.DataFrame:
    """手で数えて答え合わせできる 5 行の練習用データ。"""
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


def add_past_by_hand(df: pd.DataFrame) -> pd.DataFrame:
    """past_orders・past_cancels・前回注文からの日数を作り、元の並び順に戻して返す。"""
    ordered = df.sort_values("ordered_at")  # 時間順に並べてから数える
    ordered["past_orders"] = ordered.groupby("customer_id").cumcount()
    ordered["past_cancels"] = (
        ordered.groupby("customer_id")["is_canceled"]
        .transform(lambda s: s.shift(1).fillna(0).cumsum())  # 自分自身を含めない
    )
    # 前回の注文からの日数。1 件目は前回が無いので欠損になる（0 で埋めない）
    previous = ordered.groupby("customer_id")["ordered_at"].shift(1)
    ordered["days_since_prev_order"] = (ordered["ordered_at"] - previous).dt.days
    return ordered.sort_index()  # 学習の前に必ず元の並びへ戻す


def add_all_time_cancels(df: pd.DataFrame) -> pd.DataFrame:
    """比較用に、全期間のキャンセル数（未来を含む）も作る。"""
    out = df.copy()
    out["all_time_cancels"] = out.groupby("customer_id")["is_canceled"].transform("sum")
    return out


def main() -> None:
    # 1. 練習用データで答え合わせをする
    toy = add_all_time_cancels(add_past_by_hand(make_toy()))
    print("■ 練習用データ")
    for row in toy.itertuples():
        # 1 件目は前回の注文が無いので欠損になる。0 日と区別するために「なし」と表示する
        previous = "なし" if pd.isna(row.days_since_prev_order) else f"{row.days_since_prev_order:.0f}日"
        print(
            f"{row.order_id} {row.ordered_at:%Y-%m-%d} {row.customer_id} "
            f"is_canceled={row.is_canceled} past_orders={row.past_orders} "
            f"past_cancels={row.past_cancels:.0f} all_time_cancels={row.all_time_cancels} "
            f"前回から={previous}"
        )

    # 2. 実データに当てる
    df = load_order_table()
    past = add_all_time_cancels(add_past_by_hand(df))
    print("\n■ 実データ")
    print(f"元の表と同じ並び順に戻っているか : {past['order_id'].equals(df['order_id'])}")
    print(f"past_orders の平均 : {past['past_orders'].mean():.2f}")
    print(f"past_orders の最大 : {int(past['past_orders'].max())}")
    print(f"past_orders が 0 の行 : {int((past['past_orders'] == 0).sum()):,} 件")
    print(f"前回注文からの日数が欠損の行 : {int(past['days_since_prev_order'].isna().sum()):,} 件")
    print(f"前回注文からの日数が 0 日以上か : {bool(past['days_since_prev_order'].min() >= 0)}")
    print(f"all_time_cancels の平均 : {past['all_time_cancels'].mean():.3f}")

    # 3. 未来を混ぜていないことの確認
    not_exceed = (past["past_cancels"] <= past["all_time_cancels"]).mean()
    zero = past["all_time_cancels"] == 0
    print(f"past_cancels が all_time_cancels を超えない行の割合 : {not_exceed:.0%}")
    print(f"all_time_cancels が 0 の行のキャンセル率 : {past.loc[zero, 'is_canceled'].mean():.2%}")
    past_zero_rate = float(past.loc[past["past_cancels"] == 0, "is_canceled"].mean())
    print(f"past_cancels が 0 の行のキャンセル率も 0 になるか : {past_zero_rate == 0}"
          "（False なら答えを漏らしていない）")

    # 4. 別解：累積和から自分自身を引く書き方でも同じ結果になる
    alt = df.sort_values("ordered_at")
    cumulative = alt.groupby("customer_id")["is_canceled"].cumsum()
    alt["past_cancels"] = (cumulative - alt["is_canceled"]).astype("float64")
    alt = alt.sort_index()
    print(f"別解（累積和 − 自分自身）と一致するか : {alt['past_cancels'].equals(past['past_cancels'])}")


if __name__ == "__main__":
    main()
