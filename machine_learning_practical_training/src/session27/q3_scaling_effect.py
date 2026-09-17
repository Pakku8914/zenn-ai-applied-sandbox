"""問題3: 標準化の有無でクラスタの人数がどう変わるかを比べる。

使い方:
    docker compose exec lab python src/session27/q3_scaling_effect.py
"""

from __future__ import annotations

import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from common import FEATURES, K_MAIN, N_INIT, RANDOM_STATE, rfm_table


def run(standardize: bool) -> np.ndarray:
    """同じ条件で k-means を回す。違うのは標準化するかどうかだけ。"""
    table = rfm_table()
    X = StandardScaler().fit_transform(table) if standardize else table.to_numpy(dtype="float64")
    return KMeans(n_clusters=K_MAIN, random_state=RANDOM_STATE, n_init=N_INIT).fit(X).labels_


def spread(labels: np.ndarray) -> dict[str, float]:
    """クラスタ間で各指標の平均がどれだけ離れているかを標準偏差の単位で測る。"""
    table = rfm_table()
    stds = table.std(ddof=0)
    means = table.assign(cluster=labels).groupby("cluster")[FEATURES].mean()
    return {name: float((means[name].max() - means[name].min()) / stds[name]) for name in FEATURES}


def analyze() -> dict:
    raw_labels, scaled_labels = run(False), run(True)
    raw_counts = np.bincount(raw_labels, minlength=K_MAIN).tolist()
    scaled_counts = np.bincount(scaled_labels, minlength=K_MAIN).tolist()
    raw_spread, scaled_spread = spread(raw_labels), spread(scaled_labels)
    return {
        "raw_counts": raw_counts,
        "scaled_counts": scaled_counts,
        "raw_sorted": sorted(raw_counts, reverse=True),
        "scaled_sorted": sorted(scaled_counts, reverse=True),
        "same_counts": bool(sorted(raw_counts) == sorted(scaled_counts)),
        "raw_spread": raw_spread,
        "scaled_spread": scaled_spread,
        "raw_dominant": max(raw_spread, key=raw_spread.get),
        "scaled_effective": sum(1 for value in scaled_spread.values() if value > 1.0),
        "totals": (int(sum(raw_counts)), int(sum(scaled_counts))),
    }


def main() -> None:
    info = analyze()

    print(f"■ 1. 標準化しない場合（k={K_MAIN}・random_state={RANDOM_STATE}）")
    print(f"人数         : {info['raw_counts']}")
    print(f"多い順        : {info['raw_sorted']}")

    print("\n■ 2. 標準化した場合（ほかの条件はすべて同じ）")
    print(f"人数         : {info['scaled_counts']}")
    print(f"多い順        : {info['scaled_sorted']}")
    print(f"合計         : {info['totals'][0]:,} 人 / {info['totals'][1]:,} 人（どちらも母集団と一致）")
    print(f"人数の並びが同じか : {info['same_counts']}")

    print("\n■ 3. どの指標で分かれたか（クラスタ間の平均の差 ÷ 標準偏差）")
    print(f"{'指標':<12}{'標準化なし':>12}{'標準化あり':>12}")
    for name in FEATURES:
        print(f"{name:<12}{info['raw_spread'][name]:>12.2f}{info['scaled_spread'][name]:>12.2f}")
    print(f"標準化なしで最も離れている指標 : {info['raw_dominant']}")
    print(f"標準化ありで 1 標準偏差より離れている指標の数 : {info['scaled_effective']} / 3")

    print("\n■ 4. なぜ変わるのか")
    print("k-means はユークリッド距離で仲間を決めます。距離は差の二乗の合計なので、")
    print("円（数万）と回（1 桁）を並べると、円の差だけで距離が決まってしまいます。")
    print("標準化すると 3 指標が同じ重さになり、recency や frequency の違いも効くようになります。")


if __name__ == "__main__":
    main()
