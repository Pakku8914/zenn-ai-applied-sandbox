"""課題5: データリークをわざと作って、点検の手順を自分の手で動かす。

予測期間の注文数を特徴量に足すだけで、指標は完璧になります。
そして **警告もエラーも 1 つも出ません**。それがこの課題の要点です。

使い方:
    docker compose exec lab python src/final01/leak_audit.py
"""

from __future__ import annotations

from common import LEAK_COLUMN, TARGET, leak_audit, repeat_table


def main() -> None:
    info = leak_audit()

    print("■ 1. 期間を守ったモデル（採用する側）")
    print(f"特徴量 {info['n_features_clean']} 列 / ROC AUC {info['clean_roc_auc']:.4f} / PR-AUC {info['clean_pr_auc']:.4f}")
    print()

    print(f"■ 2. 予測期間の注文数（{LEAK_COLUMN}）を足したモデル")
    print(f"特徴量 {info['n_features_leaked']} 列 / ROC AUC {info['leaked_roc_auc']:.4f} / PR-AUC {info['leaked_pr_auc']:.4f}")
    print(f"ROC AUC の跳ね幅: +{info['gap']:.4f}")
    print("エラーも警告も出ません。ここが怖いところです。")
    print()

    print("■ 3. なぜ完璧になるのか")
    df = repeat_table()
    print(f"{LEAK_COLUMN} が 0 の顧客: {info['zero_rows']:,} 人 → そのうち再購入した人の割合 {info['zero_positive_rate']:.4f}")
    print(f"（{LEAK_COLUMN} > 0）と目的変数が完全に一致するか: {info['is_target_itself']}")
    print(f"目的変数 {TARGET} は、この列から作られています（{LEAK_COLUMN} > 0 がそのまま答え）")
    print(f"つまりモデルは答えを見ています。手元の表では {len(df):,} 行すべてで一致します。")
    print()

    print("■ 4. リークの点検チェックリスト")
    for index, item in enumerate(info["checklist"], start=1):
        print(f"[{index}] {item}")
    print()
    print("判断: 精度が完璧になったら、喜ぶ前にこの 5 項目を上から確認します。")
    print("      このプロジェクトで採用するのは、跳ねていない側の数値です。")


if __name__ == "__main__":
    main()
