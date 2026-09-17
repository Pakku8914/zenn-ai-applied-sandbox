"""問題1 の解答: ジニ係数を自分で計算して、4 つの候補から分岐を選ぶ。

使い方:
    docker compose exec lab python src/session18/q1_gini_by_hand.py
"""

from __future__ import annotations

import pandas as pd

from common import TARGET, toy_frame

# 比べる候補（列名, 表示名, 条件を作る関数）
CANDIDATES = [
    ("① unit_price <= 2000", lambda df: df["unit_price"] <= 2000),
    ("② body_length <= 120", lambda df: df["body_length"] <= 120),
    ("③ category == 実用書", lambda df: df["category"] == "実用書"),
    ("④ unit_price <= 1750", lambda df: df["unit_price"] <= 1750),
]


def gini_from_counts(n_high: int, n_low: int) -> float:
    """高評価の件数と低評価の件数からジニ係数を求める。

    ジニ係数 = 1 - p(高)^2 - p(低)^2。
    「同じ葉から 2 件を無作為に選んだとき、ラベルが食い違う確率」でもあります。
    """
    total = n_high + n_low
    if total == 0:
        return 0.0
    p_high = n_high / total
    p_low = n_low / total
    return 1.0 - p_high**2 - p_low**2


def gini_of(labels) -> float:
    """0/1 のラベル列からジニ係数を求める。"""
    values = list(labels)
    return gini_from_counts(sum(values), len(values) - sum(values))


def evaluate_split(df: pd.DataFrame, name: str, mask) -> dict:
    """条件を満たす側・満たさない側に分けて、ジニ係数の減少量を求める。"""
    total = len(df)
    left, right = df.loc[mask, TARGET], df.loc[~mask, TARGET]
    gini_left, gini_right = gini_of(left), gini_of(right)
    weighted = (len(left) / total) * gini_left + (len(right) / total) * gini_right
    return {
        "name": name,
        "n_left": len(left),
        "high_left": int(left.sum()),
        "low_left": len(left) - int(left.sum()),
        "gini_left": gini_left,
        "n_right": len(right),
        "high_right": int(right.sum()),
        "low_right": len(right) - int(right.sum()),
        "gini_right": gini_right,
        "weighted": weighted,
        "decrease": gini_of(df[TARGET]) - weighted,
    }


def main() -> None:
    df = toy_frame()
    high = int(df[TARGET].sum())
    low = len(df) - high

    print("■ 問題1: ジニ係数で分岐を選ぶ")
    print(f"全体 {len(df)} 件（高評価 {high} 件 / 低評価 {low} 件）ジニ係数 {gini_from_counts(high, low):.4f}")
    print(f"いちばん混ざった状態（10 件 / 10 件）: {gini_from_counts(10, 10):.4f}")
    print(f"まったく混ざっていない状態（20 件 / 0 件）: {gini_from_counts(20, 0):.4f}")
    print()

    results = [evaluate_split(df, name, condition(df)) for name, condition in CANDIDATES]
    print("■ 4 つの候補")
    for row in results:
        print(
            f"{row['name']} : "
            f"左 {row['n_left']} 件（{row['high_left']}/{row['low_left']}）{row['gini_left']:.4f}"
            f" / 右 {row['n_right']} 件（{row['high_right']}/{row['low_right']}）{row['gini_right']:.4f}"
            f" / 加重 {row['weighted']:.4f} / 減少 {row['decrease']:.4f}"
        )
    print()

    best = max(results, key=lambda row: row["decrease"])
    print("■ 選ばれる分岐")
    print(f"{best['name']}（減少 {best['decrease']:.4f}）")
    print("1750 は「1,700 円と 1,800 円のちょうど真ん中」です。")
    print("決定木は人が思いつく切りのよい数字ではなく、すべての境目を試して最良のものを選びます。")


if __name__ == "__main__":
    main()
