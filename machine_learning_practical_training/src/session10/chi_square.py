"""比率の差をカイ二乗検定で確かめ、関連の強さを Cramér's V で測る。

使い方:
    docker compose exec lab python src/session10/chi_square.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from common import cramers_v, format_p, load_orders


def run_chi2(table: pd.DataFrame, label: str) -> np.ndarray:
    """クロス集計表にカイ二乗検定をかけて結果を表示し、期待度数を返す。"""
    chi2, p, dof, expected = stats.chi2_contingency(table)
    print(f"■ カイ二乗検定（{label}）")
    print(f"  chi2       : {chi2:.4f}")
    print(f"  自由度     : {dof}")
    print(f"  p 値       : {format_p(p)}")
    print(f"  Cramér's V : {cramers_v(table, chi2):.4f}")
    return expected


def main() -> None:
    df = load_orders()
    table = pd.crosstab(df["channel"], df["is_canceled"])

    print(f"■ チャネル別のキャンセル（重複を除いた {len(df):,} 件）")
    print("チャネル | 有効 | キャンセル | 合計 | キャンセル率")
    for channel in table.index:
        valid, canceled = int(table.loc[channel, 0]), int(table.loc[channel, 1])
        total = valid + canceled
        print(f"{channel} | {valid:,} | {canceled:,} | {total:,} | {canceled / total:.2%}")
    print()

    # 帰無仮説 H0: キャンセル率は 4 つのチャネルで等しい（channel と is_canceled は無関係）
    expected = run_chi2(table, "channel × is_canceled")
    sns_row = list(table.index).index("SNS")
    print(f"  期待度数の最小 : {expected.min():.1f}（5 を下回るセルが無いので近似が使える）")
    print(f"  SNS のキャンセルの期待度数 : {expected[sns_row][1]:.1f}（実際は {int(table.loc['SNS', 1]):,} 件）")
    print()

    # 同じ手順を region に当てると、今度は「差があるとは言えない」結果になる
    region_table = pd.crosstab(df["region"], df["is_canceled"])
    run_chi2(region_table, "region × is_canceled")
    used = int(region_table.to_numpy().sum())
    print(f"  集計に使われた行数が {len(df):,} 件より少ないか: {used < len(df)}")
    print("  （region の欠損行は crosstab の段階で黙って除かれます。件数は必ず検算します）")


if __name__ == "__main__":
    main()
