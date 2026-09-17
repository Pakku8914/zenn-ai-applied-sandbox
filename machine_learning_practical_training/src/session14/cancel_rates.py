"""特徴量を作る前に「率」を見る。どの列に情報がありそうかを先に確かめる。

使い方:
    docker compose exec lab python src/session14/cancel_rates.py
"""

from __future__ import annotations

from common import (
    BIG_DISCOUNT_RATE,
    NEW_CUSTOMER_DAYS,
    WEEKDAY_JA,
    cancel_rate,
    load_order_table,
)


def main() -> None:
    df = load_order_table()
    print(f"母集団 : {len(df):,} 行（重複した order_id を落とした注文。キャンセルも含む）")

    # 1. 全体のキャンセル率。これが「何もしないときの当たり前」
    overall = cancel_rate(df)
    print(f"\n■ 全体のキャンセル率\n全体 : {overall:.2%}")

    # 2. 流入経路ごと。率の高い順に並べる（件数の少ないグループの率は当てにならないので後で確認する）
    print("\n■ 流入経路ごとのキャンセル率")
    by_channel = df.groupby("channel")["is_canceled"].mean().sort_values(ascending=False)
    for channel, rate in by_channel.items():
        print(f"{channel} : {rate:.2%}")

    # 3. 登録直後かどうか。「登録から 7 日未満」を境目にする（定義を必ず書き残す）
    is_new = df["days_since_signup"] < NEW_CUSTOMER_DAYS
    new_rate, old_rate = cancel_rate(df, is_new), cancel_rate(df, ~is_new)
    print(f"\n■ 登録から {NEW_CUSTOMER_DAYS} 日未満（0〜6 日）かどうか")
    print(f"登録直後の注文   : {new_rate:.2%}")
    print(f"それ以外の注文   : {old_rate:.2%}")
    print(f"倍率             : {new_rate / old_rate:.1f} 倍")

    # 4. 値引き率。20% 以上を「大きな値引き」とする
    is_big = df["discount_rate"] >= BIG_DISCOUNT_RATE
    print(f"\n■ 値引き {BIG_DISCOUNT_RATE:.0%} 以上かどうか")
    print(f"大きな値引きの注文 : {cancel_rate(df, is_big):.2%}")

    # 5. 曜日ごと。7 グループの率がどれだけばらつくかを見る
    by_weekday = df.groupby(df["ordered_at"].dt.dayofweek)["is_canceled"].mean()
    print("\n■ 曜日ごとのキャンセル率")
    for weekday, rate in by_weekday.items():
        print(f"{WEEKDAY_JA[weekday]} : {rate:.2%}")
    spread = float(by_weekday.max() - by_weekday.min())
    print(f"最小 {by_weekday.min():.2%} / 最大 {by_weekday.max():.2%}")
    print(f"最大と最小の差が 0.5 ポイント未満か : {spread < 0.005}")

    # 6. グループの大きさを必ず確認する（率だけ見て判断しない）
    #    件数の内訳そのものは df["channel"].value_counts() で見られます
    channel_counts = df["channel"].value_counts()
    print(f"\n流入経路のどのグループも 5,000 件を超えているか : {int(channel_counts.min()) > 5000}")
    print("→ 件数が十分あるので、率の差を信じてよい大きさです")

    print("\n■ ここまでの判断")
    print("・流入経路と登録からの経過日数は率が大きく動くので、特徴量にする価値がある")
    print("・曜日は率がほとんど動かないので、特徴量にしても効かないと予想できる")


if __name__ == "__main__":
    main()
