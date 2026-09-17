"""まとめ買い 118 件の素性を調べ、除外・クリッピングが数値に与える影響を比べる。

使い方:
    docker compose exec lab python src/session12/decide_treatment.py
"""

from __future__ import annotations

from common import BULK_THRESHOLD, CLIP_UPPER, add_amount, load_orders, yen


def main() -> None:
    orders = load_orders()
    quantity = orders["quantity"]
    bulk = quantity >= BULK_THRESHOLD

    print(f"■ {BULK_THRESHOLD} 冊以上の注文は何者か（重複を除いた {len(orders):,} 行）")
    print(f"件数         : {int(bulk.sum()):,} 件（全体の {bulk.mean():.1%}）・最大 {int(quantity.max())} 冊")

    # 売上はキャンセルを除き、行ごとに丸めず、合計してから整数にする（本書の売上規約）
    valid = add_amount(orders)
    valid_bulk = valid["quantity"] >= BULK_THRESHOLD
    total_amount = valid["amount"].sum()
    bulk_amount = valid.loc[valid_bulk, "amount"].sum()
    print(f"有効注文     : {int(valid_bulk.sum()):,} 件（キャンセルを除いた件数）")
    print(f"売上の構成比 : {bulk_amount / total_amount:.2%}（{yen(bulk_amount)} 円 / {yen(total_amount)} 円）")

    bulk_cancel_rate = orders.loc[bulk, "is_canceled"].mean()
    all_cancel_rate = orders["is_canceled"].mean()
    print(f"キャンセル率 : まとめ買い {bulk_cancel_rate:.2%}"
          f"（{int(orders.loc[bulk, 'is_canceled'].sum()):,} 件）/ 全体 {all_cancel_rate:.2%}")
    print(f"             → まとめ買いは全体の {bulk_cancel_rate / all_cancel_rate:.1f} 倍キャンセルされやすい")
    print()

    print("■ 処置ごとに quantity の平均がどう動くか")
    kept = quantity.loc[~bulk]
    clipped = quantity.clip(upper=CLIP_UPPER)
    print(f"そのまま               : {len(quantity):,} 件 / 平均 {quantity.mean():.4f}")
    print(f"{BULK_THRESHOLD} 冊以上を除外       : {len(kept):,} 件 / 平均 {kept.mean():.4f}")
    print(f"上限 {CLIP_UPPER} 冊でクリップ    : {len(clipped):,} 件 / 平均 {clipped.mean():.4f}")
    print()

    print("■ 除外とクリッピングの違い")
    print(f"行数の変化     : 除外は {len(quantity) - len(kept):,} 行減る / クリップは 0 行")
    print(f"最大値の変化   : 除外は {int(kept.max())} 冊まで / クリップは {int(clipped.max())} 冊まで")
    print(f"キャンセルの情報: 除外すると {int(orders.loc[bulk, 'is_canceled'].sum()):,} 件のキャンセルが"
          f"データから消える / クリップなら残る")


if __name__ == "__main__":
    main()
