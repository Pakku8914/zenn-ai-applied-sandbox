"""基準日を固定して「最終購入からの経過日数」を計算する。

使い方:
    docker compose exec lab python src/session07/recency_features.py
"""

from __future__ import annotations

import pandas as pd

from common import REFERENCE_DATE, load_valid_orders


def main() -> None:
    valid = load_valid_orders()

    # 1. 顧客ごとの最終購入日 → 基準日からの経過日数
    last_order = valid.groupby("customer_id")["ordered_at"].max()
    recency = (REFERENCE_DATE - last_order).dt.days

    print(f"基準日 : {REFERENCE_DATE:%Y-%m-%d}（コードの中で固定した「今日」）")
    print(f"有効注文のある顧客 : {len(recency):,} 人")
    print(f"経過日数の平均     : {recency.mean():.1f} 日")
    print(f"経過日数の中央値   : {int(recency.median())} 日")
    print(f"経過日数の最大     : {int(recency.max())} 日")

    # 2. 90 日以内に有効注文がある顧客を「アクティブ顧客」と呼ぶ（本書の共通ルール）
    active = recency.loc[recency <= 90]
    print(f"\n90 日以内に有効注文があった顧客（アクティブ顧客） : {len(active):,} 人")
    print(f"有効注文のある顧客 {len(recency):,} 人に対する比率 : {len(active) / len(recency):.2%}")
    print(f"全顧客 8,000 人に対する比率             : {len(active) / 8000:.2%}")

    # 3. 「今日」を実行日にすると、同じコードが実行日ごとに違う答えを返す
    #    （次の 1 行に出る数値は、実行した日によって変わります）
    today = pd.Timestamp.now().normalize()
    drifted = (today - last_order).dt.days
    print(f"\n参考 : 実行日 {today:%Y-%m-%d} を基準にすると平均 {drifted.mean():.1f} 日 / アクティブ {int((drifted <= 90).sum()):,} 人")
    print("       この 1 行は実行日によって変わります。だから本書は基準日を固定します")


if __name__ == "__main__":
    main()
