"""問題2 の解答: 15 冊以上の注文 118 件が「エラー」か「実在の注文」かを調べる。

使い方:
    docker compose exec lab python src/session12/q2_bulk_profile.py
"""

from __future__ import annotations

from common import BULK_THRESHOLD, add_amount, load_orders, yen


def main() -> None:
    orders = load_orders()
    quantity = orders["quantity"]
    bulk = quantity >= BULK_THRESHOLD

    print(f"■ {BULK_THRESHOLD} 冊以上の注文の素性（母集団 {len(orders):,} 行）")
    print(f"1. 件数     : {int(bulk.sum()):,} 件（全体の {bulk.mean():.1%}）")
    print(f"   値の範囲 : {int(quantity.loc[bulk].min())}〜{int(quantity.loc[bulk].max())} 冊")
    print(f"   4〜14 冊 : {int(quantity.between(4, 14).sum()):,} 件（ふつうの注文との間に空白がある）")

    valid = add_amount(orders)
    total_amount = valid["amount"].sum()
    bulk_amount = valid.loc[valid["quantity"] >= BULK_THRESHOLD, "amount"].sum()
    print(f"2. 売上構成比 : {bulk_amount / total_amount:.2%}"
          f"（{yen(bulk_amount)} 円 / {yen(total_amount)} 円）")

    bulk_rate = orders.loc[bulk, "is_canceled"].mean()
    all_rate = orders["is_canceled"].mean()
    print(f"3. キャンセル率 : まとめ買い {bulk_rate:.2%} / 全体 {all_rate:.2%}"
          f"（{bulk_rate / all_rate:.1f} 倍）")
    print()

    print("■ 判断（エラーではなく実在の注文である根拠）")
    print("(1) 値が連続している。入力ミスなら 1 を 11 と打つような単発の飛び値になるが、")
    print(f"    {BULK_THRESHOLD}〜{int(quantity.max())} 冊まで幅を持って分布している。")
    print("(2) 売上への寄与がある。取り除くと売上の 2.28% が消え、月次レポートの数字が変わる。")
    print("(3) 振る舞いが違う。キャンセル率が全体の約 10.8 倍で、別の買い方をしている集団に見える。")
    print("→ 結論: 記録として正しい「法人のまとめ買い」と見なし、消さずに扱い方を決める。")


if __name__ == "__main__":
    main()
