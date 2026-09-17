"""問題3: 探索空間の大きさを数え、候補の並べ方（等比か等差か）を判定する。

学習は 1 回もしません。探索を始める前の「見積もり」を作る練習です。

実行:
    docker compose exec lab python src/session23/q3_search_space.py
"""

from __future__ import annotations

from common import fit_count, space_size

CANDIDATES = {
    "① 等比（対数スケール）": [0.01, 0.02, 0.05, 0.1, 0.2],
    "② 等間隔（線形スケール）": [0.01, 0.0575, 0.105, 0.1525, 0.2],
    "③ 細かすぎる等間隔": [0.05, 0.06, 0.07, 0.08, 0.09, 0.1],
}

SPACES = {
    "A 本章のグリッド（2 × 3 × 2）": (
        {"n_estimators": [50, 200], "learning_rate": [0.02, 0.05, 0.1], "num_leaves": [7, 31]},
        None,
    ),
    "B 広い空間を総当たり（4 × 5 × 4）": (
        {
            "n_estimators": [50, 100, 200, 400],
            "learning_rate": [0.01, 0.02, 0.05, 0.1, 0.2],
            "num_leaves": [7, 15, 31, 63],
        },
        None,
    ),
    "C B から 6 通りだけ引く": (
        {
            "n_estimators": [50, 100, 200, 400],
            "learning_rate": [0.01, 0.02, 0.05, 0.1, 0.2],
            "num_leaves": [7, 15, 31, 63],
        },
        6,
    ),
}


def ratios(values: list[float]) -> list[float]:
    """隣り合う候補の倍率。"""
    return [round(float(values[i + 1] / values[i]), 4) for i in range(len(values) - 1)]


def is_geometric(values: list[float], limit: float = 1.5) -> bool:
    """倍率がだいたいそろっていれば「等比に並んでいる」と判定する。"""
    spread = max(ratios(values)) / min(ratios(values))
    return bool(spread <= limit)


def analyze() -> dict[str, object]:
    """候補の並べ方と、探索空間ごとの学習回数を数える。"""
    candidates = {
        label: {
            "values": values,
            "ratios": ratios(values),
            "spread": round(max(ratios(values)) / min(ratios(values)), 4),
            "geometric": is_geometric(values),
            # 探索範囲の広さ（いちばん大きい候補 ÷ いちばん小さい候補）
            "span": round(max(values) / min(values), 4),
        }
        for label, values in CANDIDATES.items()
    }
    spaces = {
        label: {
            "size": space_size(space),
            "n_iter": n_iter,
            "fits": fit_count(space, n_iter=n_iter),
        }
        for label, (space, n_iter) in SPACES.items()
    }
    return {
        "candidates": candidates,
        "spaces": spaces,
        "fits_ratio": spaces["B 広い空間を総当たり（4 × 5 × 4）"]["fits"] // spaces["C B から 6 通りだけ引く"]["fits"],
    }


def main() -> None:
    result = analyze()

    print("■ 1. 候補の並べ方")
    for label, info in result["candidates"].items():
        print(f"{label}")
        print(f"  候補   : {info['values']}")
        print(f"  倍率   : {info['ratios']}（最大 ÷ 最小 = {info['spread']}）")
        print(f"  等比か : {info['geometric']} / 探索範囲の広さ: {info['span']} 倍")
    print()

    print("■ 2. 探索空間ごとの学習回数（5 分割交差検証）")
    print("空間                                 | 組み合わせ | 学習回数")
    for label, info in result["spaces"].items():
        picked = "全部" if info["n_iter"] is None else f"{info['n_iter']} 通り"
        print(f"{label:<36} | {info['size']:>3} 通り ({picked:<7}) | {info['fits']:>4} 回")
    print(f"B は C の {result['fits_ratio']} 倍の学習回数")
    print()

    print("■ 3. 説明")
    print("learning_rate のような『効き方が倍率で決まる』パラメータは等比に並べます。等間隔に並べると、")
    print("小さい側の 1 歩だけが 5.75 倍もの飛躍になり、0.01〜0.05 の大事な範囲が粗くなります。")
    print("③ は倍率はそろっていますが、探索範囲が 2 倍しかないのに 6 点も使っています。")
    print("最初の探索では、点の細かさより『範囲の広さ』を優先します。")


if __name__ == "__main__":
    main()
