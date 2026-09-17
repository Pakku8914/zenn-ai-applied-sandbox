"""スケーリングの有無でクラスタリングの結果が変わることを確かめる。

使い方:
    docker compose exec lab python src/session27/scaling_matters.py
"""

from __future__ import annotations

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import FEATURES, K_MAIN, cluster_counts, labels_for, rfm_table, save_figure

FIGURE_NAME = "s27_scaling.png"


def spread_in_std_units(standardize: bool) -> dict[str, float]:
    """クラスタ間で各指標の平均がどれだけ離れているかを、標準偏差を単位にして測る。

    単位の違う 3 指標を同じ物差しで比べるために、「何標準偏差ぶん離れているか」に
    直します。値が小さい指標は、そのクラスタリングに効いていないということです。
    """
    table = rfm_table()
    stds = table.std(ddof=0)  # StandardScaler と同じ計算（ddof=0）
    means = table.assign(cluster=np.asarray(labels_for(K_MAIN, standardize))).groupby("cluster")[FEATURES].mean()
    return {name: float((means[name].max() - means[name].min()) / stds[name]) for name in FEATURES}


def analyze() -> dict:
    """生のまま回した場合と標準化してから回した場合を並べる。"""
    table = rfm_table()
    stds = {name: float(table[name].std(ddof=0)) for name in FEATURES}
    raw_spread = spread_in_std_units(False)
    scaled_spread = spread_in_std_units(True)
    others = max(stds["recency"], stds["frequency"])
    return {
        "stds": stds,
        "monetary_dominates_scale": bool(stds["monetary"] > others * 10),
        "raw_counts": cluster_counts(K_MAIN, False),
        "scaled_counts": cluster_counts(K_MAIN, True),
        "raw_min": min(cluster_counts(K_MAIN, False)),
        "scaled_min": min(cluster_counts(K_MAIN, True)),
        # 番号には対応関係がないので、多い順にそろえてから比べる
        "same_counts": bool(
            sorted(cluster_counts(K_MAIN, False)) == sorted(cluster_counts(K_MAIN, True))
        ),
        "raw_spread": raw_spread,
        "scaled_spread": scaled_spread,
        "raw_dominant": max(raw_spread, key=raw_spread.get),
        "scaled_effective": sum(1 for value in scaled_spread.values() if value > 1.0),
    }


def draw(info: dict) -> str:
    """2 通りのクラスタの大きさを、人数の多い順に並べて見比べる。"""
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.2), sharey=True)
    pairs = [
        (axes[0], sorted(info["raw_counts"], reverse=True), "標準化しない（生の 3 指標）", "#e45756"),
        (axes[1], sorted(info["scaled_counts"], reverse=True), "標準化してから k-means", "#4c78a8"),
    ]
    for ax, counts, title, color in pairs:
        ax.bar([f"大きさ{i + 1}位" for i in range(len(counts))], counts, color=color)
        ax.set_title(title)
        ax.set_ylabel("人数")
        ax.grid(alpha=0.3, axis="y")
        for index, value in enumerate(counts):
            ax.text(index, value, f"{value:,}", ha="center", va="bottom")
    fig.suptitle(f"同じデータ・同じ k={K_MAIN}・同じ random_state でも、スケーリングの有無で分かれ方が変わる")
    fig.tight_layout()
    save_figure(fig, FIGURE_NAME)
    plt.close(fig)
    return FIGURE_NAME


def main() -> None:
    info = analyze()

    print("■ 1. 3 指標のばらつきの大きさ（単位が違うので比べられない）")
    for name in FEATURES:
        print(f"  {name:<10}標準偏差 {info['stds'][name]:>12,.2f}")
    print(f"monetary の標準偏差が、ほかの 2 指標の 10 倍より大きいか : {info['monetary_dominates_scale']}")
    print("→ 距離は差の二乗の合計なので、このままでは monetary の差だけで距離が決まる")

    print(f"\n■ 2. 生の 3 指標をそのまま k-means に渡す（k={K_MAIN}）")
    print(f"人数 : {info['raw_counts']}")
    print(f"いちばん小さいクラスタ : {info['raw_min']:,} 人")

    print("\n■ 3. 標準化してから k-means に渡す（ほかの条件はすべて同じ）")
    print(f"人数 : {info['scaled_counts']}")
    print(f"いちばん小さいクラスタ : {info['scaled_min']:,} 人")
    print(f"人数の並びが同じか : {info['same_counts']}")

    print("\n■ 4. どの指標で分かれているか（クラスタ間の平均の差／標準偏差）")
    print(f"{'指標':<12}{'生のまま':>12}{'標準化後':>12}")
    for name in FEATURES:
        print(f"{name:<12}{info['raw_spread'][name]:>12.2f}{info['scaled_spread'][name]:>12.2f}")
    print(f"生のままで最も離れている指標 : {info['raw_dominant']}")
    print(f"標準化後に 1 標準偏差より大きく離れている指標の数 : {info['scaled_effective']} / 3")

    print("\n■ 5. 結論")
    print("セッション12 では『スケーリングしても AUC はほとんど変わらない』と確かめました。")
    print("しかしクラスタリングでは、スケーリングが結果そのものを決めます。")
    print("距離で仲間を決めるアルゴリズムでは、標準化は『やったほうがよい』ではなく前提条件です。")

    print(f"\n図を保存しました: outputs/{draw(info)}")


if __name__ == "__main__":
    main()
