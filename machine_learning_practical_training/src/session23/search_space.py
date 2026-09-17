"""探索範囲の決め方 ― 対数スケールで粗く張る（本文 3 節）。

ここでは**モデルを 1 回も学習しません**。「どう並べるか」「何回になるか」を
先に数えるだけのスクリプトです。探索を始める前にこれをやるのが肝心です。

実行:
    docker compose exec lab python src/session23/search_space.py
"""

from __future__ import annotations

import numpy as np

from common import N_SPLITS, fit_count, space_size

# 等比（対数スケール）に並べた learning_rate の候補 ― 本書の推奨
LOG_RATES = [0.01, 0.02, 0.05, 0.1, 0.2]
# 等間隔（線形スケール）に並べた同じ範囲の 5 点 ― こちらは端に偏る
LINEAR_RATES = [round(float(value), 4) for value in np.linspace(0.01, 0.2, 5)]

# 探索計画の候補（組み合わせ数がどう増えるかを見るための机上の計算）
PLANS = [
    ("① 本章のグリッド（2 × 3 × 2）", {"n_estimators": [50, 200], "learning_rate": [0.02, 0.05, 0.1], "num_leaves": [7, 31]}, None),
    ("② learning_rate を 1 つ足す（2 × 4 × 2）", {"n_estimators": [50, 200], "learning_rate": [0.02, 0.05, 0.1, 0.2], "num_leaves": [7, 31]}, None),
    ("③ 3 つとも 5 候補にする（5 × 5 × 5）", {"n_estimators": [50, 100, 200, 400, 800], "learning_rate": LOG_RATES, "num_leaves": [7, 15, 31, 63, 127]}, None),
    ("④ ランダムサーチの空間を総当たり（4 × 5 × 4）", {"n_estimators": [50, 100, 200, 400], "learning_rate": LOG_RATES, "num_leaves": [7, 15, 31, 63]}, None),
    ("⑤ ④ の空間から 6 通りだけ引く", {"n_estimators": [50, 100, 200, 400], "learning_rate": LOG_RATES, "num_leaves": [7, 15, 31, 63]}, 6),
]


def ratios(values: list[float]) -> list[float]:
    """隣り合う候補の「倍率」を返す。等比に並んでいれば同じ数がそろう。"""
    return [round(float(values[i + 1] / values[i]), 4) for i in range(len(values) - 1)]


def plan_table() -> list[dict]:
    """探索計画ごとに、組み合わせ数と学習回数を数える。"""
    rows = []
    for label, space, n_iter in PLANS:
        rows.append(
            {
                "label": label,
                "size": space_size(space),
                "n_iter": n_iter,
                "fits": fit_count(space, n_splits=N_SPLITS, n_iter=n_iter),
            }
        )
    return rows


def main() -> None:
    print("■ learning_rate の並べ方")
    print(f"等比（対数スケール）: {LOG_RATES}")
    print(f"  隣との倍率        : {ratios(LOG_RATES)}")
    print(f"等間隔（線形スケール）: {LINEAR_RATES}")
    print(f"  隣との倍率        : {ratios(LINEAR_RATES)}")
    print("等間隔だと、いちばん左の 1 歩だけが 5.75 倍もの大きな飛躍になります。")
    print()

    print("■ 探索計画ごとの学習回数（5 分割交差検証）")
    print("計画                                         | 組み合わせ | 学習回数")
    for row in plan_table():
        n_iter = "全部" if row["n_iter"] is None else f"{row['n_iter']} 通り"
        print(f"{row['label']:<44} | {row['size']:>4} 通り ({n_iter:<7}) | {row['fits']:>4} 回")
    print()
    print("候補を 1 つ足すだけで学習回数が跳ね上がります（掛け算で増えるため）。")


if __name__ == "__main__":
    main()
