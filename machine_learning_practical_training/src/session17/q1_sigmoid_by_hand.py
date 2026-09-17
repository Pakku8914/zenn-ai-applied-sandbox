"""問題1 の解答: 確率・オッズ・対数オッズを自分の手で行き来する。

使い方:
    docker compose exec lab python src/session17/q1_sigmoid_by_hand.py
"""

from __future__ import annotations

import math

# 表示する対数オッズと確率の代表値
LOGITS = [-3, -2, -1, 0, 1, 2, 3]
PROBABILITIES = [0.2, 0.5, 0.8, 0.9]
# 本文で求めた pages のオッズ比（1 標準偏差あたり）
PAGES_ODDS_RATIO = 3.6723
# オッズ比を掛ける前の確率（同じ倍率でも動き方が違うことを見る）
START_PROBABILITIES = [0.5, 0.9]


def sigmoid(z: float) -> float:
    """対数オッズ z を確率に変える。math.exp を使うので引数はスカラーだけ。"""
    return 1.0 / (1.0 + math.exp(-z))


def to_odds(p: float) -> float:
    """確率をオッズに変える（起こる回数 : 起こらない回数）。"""
    return p / (1.0 - p)


def to_probability(odds: float) -> float:
    """オッズを確率に戻す。"""
    return odds / (1.0 + odds)


def to_logit(p: float) -> float:
    """確率を対数オッズに変える。"""
    return math.log(to_odds(p))


def apply_odds_ratio(p: float, odds_ratio: float) -> float:
    """確率 p の人のオッズを odds_ratio 倍したときの確率を返す。"""
    return to_probability(to_odds(p) * odds_ratio)


def main() -> None:
    print("■ 対数オッズ → 確率（シグモイド）")
    for z in LOGITS:
        print(f"z = {z:+d} → 確率 {sigmoid(z):.4f}")
    print()

    print("■ 確率 → オッズ → 対数オッズ → 確率")
    for p in PROBABILITIES:
        z = to_logit(p)
        print(f"確率 {p:.2f} / オッズ {to_odds(p):.4f} / 対数オッズ {z:+.4f} / 戻した確率 {sigmoid(z):.4f}")
    round_trip_ok = all(abs(sigmoid(to_logit(p)) - p) < 1e-12 for p in PROBABILITIES)
    print(f"1 周して元の確率に戻るか: {round_trip_ok}")
    print()

    print(f"■ オッズ比 {PAGES_ODDS_RATIO} を掛けると確率はどう動くか")
    for p in START_PROBABILITIES:
        after = apply_odds_ratio(p, PAGES_ODDS_RATIO)
        print(f"確率 {p:.2f}（オッズ {to_odds(p):.4f}）→ 確率 {after:.4f}（オッズ {to_odds(after):.4f}）")
    print("→ オッズは決まった倍率で動きますが、確率の増え方は元の確率によって変わります。")


if __name__ == "__main__":
    main()
