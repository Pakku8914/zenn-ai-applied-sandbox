"""問題4 の解答: PSI を自分で実装し、監視したい 4 列を測る。

使い方:
    docker compose exec lab python src/session28/q4_psi_table.py
"""

from __future__ import annotations

import numpy as np

from common import (
    PSI_BINS,
    PSI_FLOOR,
    PSI_WATCH,
    SPLIT_DATE,
    cancel_rates,
    halves,
    psi_table,
    verdict,
)


def psi_by_hand(expected, actual, bins: int = PSI_BINS) -> float:
    """PSI を 1 行ずつ組み立てて計算する（common.psi と同じ値になることを確かめる用）。"""
    expected = np.asarray(expected, dtype="float64")
    actual = np.asarray(actual, dtype="float64")

    edges = np.unique(np.quantile(expected, np.linspace(0.0, 1.0, bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf

    expected_counts, _ = np.histogram(expected, bins=edges)
    actual_counts, _ = np.histogram(actual, bins=edges)
    expected_shares = np.clip(expected_counts / expected_counts.sum(), PSI_FLOOR, None)
    actual_shares = np.clip(actual_counts / actual_counts.sum(), PSI_FLOOR, None)
    return float(np.sum((actual_shares - expected_shares) * np.log(actual_shares / expected_shares)))


def analyze() -> dict:
    """PSI の表と、自作の計算が一致するかをまとめる。"""
    parts = halves()
    table = psi_table()
    by_hand = {
        str(row.column): psi_by_hand(parts["before"][row.column], parts["after"][row.column])
        for row in table.itertuples()
    }
    matches = all(
        abs(by_hand[str(row.column)] - row.psi) < 1e-12 for row in table.itertuples()
    )
    worst = table.loc[table["psi"].idxmax()]
    return {
        "rates": cancel_rates(),
        "table": table,
        "by_hand": by_hand,
        "matches": bool(matches),
        "worst_column": str(worst["column"]),
        "worst_psi": float(worst["psi"]),
        "n_stable": int((table["psi"] < PSI_WATCH).sum()),
        "n_columns": int(len(table)),
    }


def main() -> None:
    result = analyze()
    rates = result["rates"]
    table = result["table"]

    print(f"■ 1. 前半と後半に分ける（境目 {SPLIT_DATE.date()}）")
    print(
        f"前半: 注文 {rates['before_n']:,} 件 / 有効注文 {rates['before_valid']:,} 件"
        f" / キャンセル率 {rates['before_rate']:.4f}"
    )
    print(
        f"後半: 注文 {rates['after_n']:,} 件 / 有効注文 {rates['after_valid']:,} 件"
        f" / キャンセル率 {rates['after_rate']:.4f}"
    )
    print(f"キャンセル率の差: {rates['after_rate'] - rates['before_rate']:+.4f}")
    print()

    print(f"■ 2. {result['n_columns']} 列の PSI")
    print("列            |    PSI | 判定")
    for row in table.itertuples():
        print(f"{row.column:<14}| {row.psi:>6.4f} | {row.judgement}")
    print(f"最大: {result['worst_psi']:.4f}（{result['worst_column']}）")
    print(f"{PSI_WATCH} 未満の列: {result['n_stable']} / {result['n_columns']}")
    print(f"自作の計算と一致: {result['matches']}")
    print()

    price = table.loc[table["column"] == "unit_price"].iloc[0]
    print("■ 3. 単価の平均")
    print(
        f"前半 {price['before_mean']:,.2f} 円 → 後半 {price['after_mean']:,.2f} 円"
        f"（差 {price['after_mean'] - price['before_mean']:+,.2f} 円）"
    )
    print(f"判定: {verdict(float(price['psi']))}")
    print()

    print("■ 4. PSI が 0 に近いことの意味（3 文）")
    print("分布がほとんど動いていないので、モデルは学習時と同じ形の入力を受け取っています。")
    print("つまり「入力が変わったせいで予測が外れる」という筋書きは、いまは成り立ちません。")
    print("ただしそれは、この指標が動くことを確かめてから言えることです（次の問題）。")


if __name__ == "__main__":
    main()
