"""クラスタ数 k を決める 2 つの指標（エルボーとシルエット）を並べて比べる。

使い方:
    docker compose exec lab python src/session27/choose_k.py
"""

from __future__ import annotations

import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import K_MAIN, SILHOUETTE_SAMPLE, best_k_by_silhouette, save_figure, sweep_table

ELBOW_FIGURE = "s27_elbow.png"
SILHOUETTE_FIGURE = "s27_silhouette.png"


def analyze() -> dict:
    """k=2〜6 の inertia とシルエット係数、そして『どちらの指標が何を指すか』を返す。"""
    table = sweep_table()
    best = best_k_by_silhouette()
    drops = [float(value) for value in table["inertia_drop"].dropna()]
    # 折れ目（エルボー）があるなら、その手前で「次の減り方 ÷ いまの減り方」がぐっと小さくなる
    ratios = [round(drops[i + 1] / drops[i], 3) for i in range(len(drops) - 1)]
    return {
        "rows": table.to_dict("records"),
        "best_k_by_silhouette": best,
        "drops": drops,
        "drop_ratios": ratios,
        "min_inertia_k": int(table.loc[table["inertia"].idxmin(), "k"]),
        "silhouette_at_main": float(table.loc[table["k"] == K_MAIN, "silhouette"].iloc[0]),
        "silhouette_best": float(table["silhouette"].max()),
    }


def draw(rows: list[dict], best: int) -> tuple[str, str]:
    """エルボー図とシルエットの推移を別々の図に保存する。"""
    ks = [row["k"] for row in rows]
    inertias = [row["inertia"] for row in rows]
    scores = [row["silhouette"] for row in rows]

    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    ax.plot(ks, inertias, marker="o", color="#4c78a8")
    ax.set_xlabel("クラスタ数 k")
    ax.set_ylabel("inertia（中心までの距離の二乗の合計）")
    ax.set_title("エルボー図：どこで折れているか決められない")
    ax.set_xticks(ks)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    save_figure(fig, ELBOW_FIGURE)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    colors = ["#f58518" if k == best else "#4c78a8" for k in ks]
    ax.bar([str(k) for k in ks], scores, color=colors)
    ax.set_xlabel("クラスタ数 k")
    ax.set_ylabel(f"シルエット係数（sample_size={SILHOUETTE_SAMPLE}）")
    ax.set_title(f"シルエット係数：k={best} が最大（橙）")
    ax.set_ylim(0.0, 0.6)
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    save_figure(fig, SILHOUETTE_FIGURE)
    plt.close(fig)
    return ELBOW_FIGURE, SILHOUETTE_FIGURE


def main() -> None:
    info = analyze()

    print("■ 1. k を変えて 2 つの指標を測る")
    print(f"{'k':>3}{'inertia':>12}{'次の k での減り方':>18}{'シルエット係数':>16}")
    for row in info["rows"]:
        drop = float(row["inertia_drop"])
        drop_text = "—" if math.isnan(drop) else f"{drop:,.1f}"  # k=6 の行は「次の k」がないので NaN
        print(f"{int(row['k']):>3}{float(row['inertia']):>12,.1f}{drop_text:>18}{float(row['silhouette']):>16.4f}")

    print("\n■ 2. エルボー法の読み方")
    print(f"減り方 : {' → '.join(f'{value:,.1f}' for value in info['drops'])}")
    print(f"減り方の比 : {' → '.join(f'{value:.2f}' for value in info['drop_ratios'])}")
    print("→ 折れ目があるなら、その手前で比がぐっと小さくなる（減り方が一気に鈍る）")
    print("→ この表は比が 0.4 より下がらず、後ろほど 1 に近づく。段差がなく、なめらかに下がっている")
    print(f"inertia は k を増やすほど必ず下がるので、最小の k は常に最大の k（この表では {info['min_inertia_k']}）")

    print("\n■ 3. シルエット係数の読み方")
    print(f"最大値 : {info['silhouette_best']:.4f}（k={info['best_k_by_silhouette']}）")
    print(f"k={K_MAIN} のときの値 : {info['silhouette_at_main']:.4f}")
    print("→ シルエットは『増やせば良くなる』指標ではないので、山の位置が答えの候補になる")

    print("\n■ 4. 2 つの指標が違う答えを出した")
    print("エルボーは決められない・シルエットは k=3 が最良。これは珍しいことではありません。")
    print("教師なし学習には正解がないので、指標は『候補を絞る道具』として使い、最後は目的で決めます。")

    elbow, silhouette = draw(info["rows"], info["best_k_by_silhouette"])
    print(f"\n図を保存しました: outputs/{elbow} と outputs/{silhouette}")


if __name__ == "__main__":
    main()
