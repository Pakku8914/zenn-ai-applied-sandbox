"""問題6 の解答: 目的別に処置を選び、根拠となる数値つきの Markdown 表を出力する。

使い方:
    docker compose exec lab python src/session12/q6_decision_report.py > outputs/s12_report.md
"""

from __future__ import annotations

import numpy as np

from common import BULK_THRESHOLD, CLIP_UPPER, add_amount, load_orders, yen


def main() -> None:
    orders = load_orders()
    quantity = orders["quantity"]
    bulk = quantity >= BULK_THRESHOLD

    valid = add_amount(orders)
    total_amount = valid["amount"].sum()
    bulk_amount = valid.loc[valid["quantity"] >= BULK_THRESHOLD, "amount"].sum()
    share = bulk_amount / total_amount
    bulk_rate = orders.loc[bulk, "is_canceled"].mean()
    all_rate = orders["is_canceled"].mean()
    logged = np.log1p(quantity)

    print(f"# quantity の外れ値 {int(bulk.sum())} 件をどう扱うか")
    print()
    print(f"- 母集団: 重複を除いた {len(orders):,} 行")
    print(f"- 対象: {BULK_THRESHOLD} 冊以上の注文 {int(bulk.sum())} 件（最大 {int(quantity.max())} 冊）")
    print()
    print("| 目的 | 選ぶ処置 | 根拠となる数値 |")
    print("| :--- | :--- | :--- |")
    print(f"| 月次の売上レポート | そのまま使う | 除外すると売上の {share:.2%}"
          f"（{yen(bulk_amount)} 円）が消える |")
    print(f"| キャンセル予測のモデル | そのまま、または上限 {CLIP_UPPER} 冊でクリップ |"
          f" まとめ買いのキャンセル率 {bulk_rate:.2%} は全体 {all_rate:.2%} の"
          f" {bulk_rate / all_rate:.1f} 倍。除外すると予測に効く情報が消える |")
    print(f"| 「ふつうの注文冊数」の報告 | 処置せず中央値で報告する | 平均 {quantity.mean():.4f} に対し"
          f" 中央値 {quantity.median():.1f}・最頻値 {int(quantity.mode().iloc[0])} |")
    print(f"| 線形モデルの特徴量にする | log1p 変換 | 歪度 {quantity.skew():.4f} →"
          f" {logged.skew():.4f} に下がる |")
    print("| 木モデルの特徴量にする | そのまま使う | 分割は大小関係だけを見るので変換の効果が小さい |")
    print()
    print("## 除外してよい場合")
    print()
    print("- 値が記録として誤っていると確認できた場合（同じ注文 ID に矛盾がある、など）")
    print(f"- 本書のデータでは 4〜14 冊の注文が {int(quantity.between(4, 14).sum())} 件で、"
          f"{BULK_THRESHOLD} 冊以上は連続した値の集団になっている。入力ミスの形をしていない")
    print()
    print("## 申し送り")
    print()
    print("- 処置を決めたら、その処置を「検証データにも同じ基準で」適用する")
    print(f"- クリッピングの上限（{CLIP_UPPER} 冊）は訓練データから決め、検証データにも同じ値を使う")


if __name__ == "__main__":
    main()
