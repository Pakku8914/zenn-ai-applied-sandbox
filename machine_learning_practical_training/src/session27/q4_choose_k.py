"""問題4: k=2〜6 の inertia とシルエット係数を並べ、2 つの指標の答えを比べる。

使い方:
    docker compose exec lab python src/session27/q4_choose_k.py
"""

from __future__ import annotations

import matplotlib
import pandas as pd
from sklearn.metrics import silhouette_score

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    K_RANGE,
    N_INIT,
    RANDOM_STATE,
    SILHOUETTE_SAMPLE,
    fit_kmeans,
    save_figure,
    scaled_matrix,
)

FIGURE_NAME = "s27_q4_choose_k.png"


def sweep() -> pd.DataFrame:
    """k を変えながら 2 つの指標を測る（条件は k 以外すべて同じにする）。"""
    X = scaled_matrix()
    rows = []
    for k in K_RANGE:
        model = fit_kmeans(X, k)
        rows.append(
            {
                "k": k,
                "inertia": float(model.inertia_),
                "silhouette": float(
                    silhouette_score(
                        X, model.labels_, sample_size=SILHOUETTE_SAMPLE, random_state=RANDOM_STATE
                    )
                ),
            }
        )
    return pd.DataFrame(rows)


def analyze() -> dict:
    table = sweep()
    drops = [
        float(table.loc[i, "inertia"] - table.loc[i + 1, "inertia"]) for i in range(len(table) - 1)
    ]
    return {
        "rows": table.to_dict("records"),
        "drops": drops,
        "drop_ratios": [drops[i + 1] / drops[i] for i in range(len(drops) - 1)],
        "best_k": int(table.loc[table["silhouette"].idxmax(), "k"]),
        "worst_k": int(table.loc[table["silhouette"].idxmin(), "k"]),
        "inertia_is_monotonic": bool(all(a > b for a, b in zip(table["inertia"], table["inertia"][1:]))),
        "silhouette_is_monotonic": bool(
            all(a > b for a, b in zip(table["silhouette"], table["silhouette"][1:]))
        ),
    }


def draw(rows: list[dict], best: int) -> str:
    """エルボー図とシルエットの推移を 1 枚に並べる。"""
    ks = [row["k"] for row in rows]
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.2))
    axes[0].plot(ks, [row["inertia"] for row in rows], marker="o", color="#4c78a8")
    axes[0].set_title("エルボー図（inertia）")
    axes[0].set_xlabel("クラスタ数 k")
    axes[0].set_ylabel("inertia")
    axes[0].set_xticks(ks)
    axes[1].plot(ks, [row["silhouette"] for row in rows], marker="o", color="#f58518")
    axes[1].axvline(best, color="#999999", linestyle="--")
    axes[1].set_title(f"シルエット係数（最大は k={best}）")
    axes[1].set_xlabel("クラスタ数 k")
    axes[1].set_ylabel("シルエット係数")
    axes[1].set_xticks(ks)
    axes[1].set_ylim(0.0, 0.6)
    for ax in axes:
        ax.grid(alpha=0.3)
    fig.suptitle("2 つの指標は違う答えを出す（同じデータ・同じ条件）")
    fig.tight_layout()
    save_figure(fig, FIGURE_NAME)
    plt.close(fig)
    return FIGURE_NAME


def main() -> None:
    info = analyze()

    print(f"■ 1. k を変えて測る（random_state={RANDOM_STATE}・n_init={N_INIT}）")
    print(f"{'k':>3}{'inertia':>12}{'シルエット係数':>16}")
    for row in info["rows"]:
        print(f"{int(row['k']):>3}{float(row['inertia']):>12,.1f}{float(row['silhouette']):>16.4f}")

    print("\n■ 2. inertia の減り方")
    print(f"減り方 : {' → '.join(f'{value:,.1f}' for value in info['drops'])}")
    print(f"減り方の比 : {' → '.join(f'{value:.2f}' for value in info['drop_ratios'])}")
    print(f"inertia は k を増やすと必ず下がるか : {info['inertia_is_monotonic']}")
    print(f"シルエット係数も同じように単調に動くか : {info['silhouette_is_monotonic']}")

    print("\n■ 3. 2 つの指標の答え")
    print("エルボー : はっきり折れる点がないので、この図からは決められない")
    print(f"シルエット : k={info['best_k']} が最大（最小は k={info['worst_k']}）")

    print("\n■ 4. 結論")
    print("エルボー法で決まらないことは珍しくありません。inertia は k を増やせば必ず下がるので、")
    print("『下がり方が鈍る点』が無い形のデータでは、この方法は答えを出しません。")
    print("シルエット係数は山の位置が候補になりますが、それも『まとまり具合』だけの評価です。")
    print("最後は目的（運用できるセグメントの数）で決めます。")

    print(f"\n図を保存しました: outputs/{draw(info['rows'], info['best_k'])}")


if __name__ == "__main__":
    main()
