"""問題1: 不純度ベースの重要度を split と gain の 2 通りで並べ、順位の違いを確かめる。

使い方:
    docker compose exec lab python src/session26/q1_impurity_ranks.py
"""

from __future__ import annotations

from common import impurity_table

TOP_N = 5


def summary() -> dict:
    """split と gain の並びをまとめ、順位が入れ替わるかを判定する。"""
    table = impurity_table()
    split_order = list(table.sort_values("split", ascending=False)["feature"])
    gain_order = list(table.sort_values("gain", ascending=False)["feature"])
    return {
        "table": table,
        "n_columns": len(table),
        "split_total": int(table["split"].sum()),
        "split_order": split_order,
        "gain_order": gain_order,
        "same_first": split_order[0] == gain_order[0],
        "same_order": split_order == gain_order,
    }


def main() -> None:
    result = summary()
    table = result["table"]

    print(f"■ 1. split（分割に使われた回数）― 変換後の {result['n_columns']} 列すべて")
    print(f"{'順位':<4}{'特徴量':<16}{'split':>7}")
    for row in table.sort_values("split", ascending=False).itertuples(index=False):
        print(f"{str(row.split_rank) + '位':<4}{row.feature:<16}{row.split:>7,}")
    print(f"合計: {result['split_total']:,}")
    print()

    print(f"■ 2. gain（分割で減った不純度の合計）― 上位 {TOP_N} 件")
    print(f"{'順位':<4}{'特徴量':<16}{'gain':>9}")
    for row in table.sort_values("gain", ascending=False).head(TOP_N).itertuples(index=False):
        print(f"{str(row.gain_rank) + '位':<4}{row.feature:<16}{int(row.gain):>9,}")
    print()

    print("■ 3. 判定")
    print(f"split の 1 位: {result['split_order'][0]}")
    print(f"gain の 1 位 : {result['gain_order'][0]}")
    print(f"1 位が同じか : {result['same_first']}")
    print(f"並びが同じか : {result['same_order']}")
    print()
    print("説明: split は『何回使ったか』、gain は『使ったときにどれだけ迷いが減ったか』です。")
    print("      body_length は細かく何度も使われ、unit_price は 1 回の分割で大きく効きます。")
    print("      だから同じモデルでも 1 位が入れ替わります。どちらを見ているか必ず書きます。")


if __name__ == "__main__":
    main()
