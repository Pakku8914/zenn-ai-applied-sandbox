"""課題1 の解答: 母集団と分割を固定し、ベースラインを先に置く。

実行:
    docker compose exec lab python src/mid02/explore.py
"""

from __future__ import annotations

from common import baseline_scores, describe_split, load_order_table, split_xy


def summary() -> dict[str, object]:
    """母集団・分割・ベースラインをまとめて返す（レポートの先頭に書く数値）。"""
    df = load_order_table()
    counts = describe_split(df)
    _, _, _, y_test = split_xy(df)
    return {**counts, "baseline": baseline_scores(y_test)}


def main() -> None:
    result = summary()
    base = result["baseline"]

    print("■ 1. 母集団（重複した order_id を落とした注文）")
    print(f"行数        : {result['n_rows']:,} 件")
    print(f"キャンセル  : {result['n_positive']:,} 件（正例率 {result['rate_all']:.4f}）")
    print()

    print("■ 2. 分割（test_size=0.25 / random_state=42 / stratify=y）")
    print(f"訓練        : {result['n_train']:,} 件（正例 {result['n_train_positive']:,}"
          f" / 負例 {result['n_train_negative']:,}・正例率 {result['rate_train']:.4f}）")
    print(f"評価        : {result['n_test']:,} 件（正例 {result['n_test_positive']:,}"
          f"・正例率 {result['rate_test']:.4f}）")
    print()

    print("■ 3. ベースライン（全部「キャンセルされない」と予測する）")
    print(f"accuracy    : {base['accuracy']:.4f}")
    print(f"ROC AUC     : {base['roc_auc']:.4f}")
    print(f"PR-AUC      : {base['pr_auc']:.4f}（= 評価データの正例率）")
    print()

    print("■ 4. この数字の意味")
    print(f"accuracy {base['accuracy']:.4f} は「1 件も当てない予測」で取れる値です。")
    print("モデルの accuracy がこれと同じでも、性能があるとは言えません。")


if __name__ == "__main__":
    main()
