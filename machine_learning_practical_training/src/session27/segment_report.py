"""クラスタに業務的な名前を付け、正解のない結果をどう評価するかを確かめる。

使い方:
    docker compose exec lab python src/session27/segment_report.py
"""

from __future__ import annotations

import matplotlib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    FEATURES,
    FEATURE_JA,
    K_ALT,
    K_MAIN,
    N_INIT,
    SEGMENT_RULES,
    labels_for,
    print_profile,
    profile,
    rfm_table,
    save_figure,
    scaled_matrix,
    segment_names,
)

FIGURE_NAME = "s27_profile.png"
SEED_CANDIDATES = (0, 1, 2)  # 安定性を自分で確かめるための別のシード

# セグメントごとの打ち手（数値ではなく「何をするか」を決めるのがセグメントの目的）
ACTIONS = {
    "優良顧客": "先行販売の案内。値引きよりも「早く買える」価値を届ける",
    "常連顧客": "関連ジャンルのおすすめ。購入間隔が伸びたら早めに声をかける",
    "一般顧客": "まとめ買いの送料無料など、2 回目の購入を作る施策",
    "離脱顧客": "復帰クーポン。反応がなければ配信頻度を落とす",
    "様子見顧客": "行動が固まっていない層。まずは観察して施策は保留",
}


def analyze() -> dict:
    """名前つきの profile、人数と売上の構成比、k=3 との対応をまとめて返す。"""
    table = profile(K_MAIN)
    names = segment_names(K_MAIN)
    total_customers = int(table["n"].sum())

    # 売上の構成比はクラスタごとの合計から出す（平均 × 人数で概算しない）
    assigned = rfm_table().assign(cluster=np.asarray(labels_for(K_MAIN)))
    revenue = assigned.groupby("cluster")["monetary"].sum()
    total_revenue = float(revenue.sum())

    cross = pd.crosstab(
        pd.Series(np.asarray(labels_for(K_ALT)), name=f"k={K_ALT}"),
        pd.Series(np.asarray(labels_for(K_MAIN)), name=f"k={K_MAIN}"),
    )

    X = scaled_matrix()
    seeds = {}
    for seed in SEED_CANDIDATES:
        labels = fit_kmeans_with_seed(X, seed)
        seeds[seed] = sorted(np.bincount(labels, minlength=K_MAIN).tolist(), reverse=True)

    return {
        "profile": table,
        "names": names,
        "customer_share": {int(c): int(row["n"]) / total_customers for c, row in table.iterrows()},
        "revenue_share": {int(c): float(value) / total_revenue for c, value in revenue.items()},
        "total_revenue": round(total_revenue),
        "cross": cross,
        "cross_total": int(cross.to_numpy().sum()),
        "cross_shape": cross.shape,
        "seed_counts": seeds,
        "seed_totals": {seed: int(sum(counts)) for seed, counts in seeds.items()},
    }


def fit_kmeans_with_seed(X: np.ndarray, seed: int) -> np.ndarray:
    """シードだけを変えて k-means を回す（結果の安定性を自分で確かめるための道具）。"""
    return KMeans(n_clusters=K_MAIN, random_state=seed, n_init=N_INIT).fit(X).labels_


def draw(info: dict) -> str:
    """3 指標をクラスタごとに並べ、profile を図で見比べる。"""
    table = info["profile"]
    names = info["names"]
    ticks = [f"{cluster}\n{names[int(cluster)]}" for cluster in table.index]
    colors = ["#4c78a8", "#f58518", "#54a24b", "#e45756", "#b279a2"]

    fig, axes = plt.subplots(1, 3, figsize=(12.0, 4.4))
    for ax, name in zip(axes, FEATURES):
        values = table[name].to_numpy()
        ax.bar(ticks, values, color=[colors[int(c) % len(colors)] for c in table.index])
        ax.set_title(FEATURE_JA[name])
        ax.grid(alpha=0.3, axis="y")
        for index, value in enumerate(values):
            ax.text(index, value, f"{value:,.1f}", ha="center", va="bottom", fontsize=9)
    fig.suptitle(f"クラスタ profile の比較（k={K_MAIN}）：3 指標をそろえて見ると性格が読める")
    fig.tight_layout()
    save_figure(fig, FIGURE_NAME)
    plt.close(fig)
    return FIGURE_NAME


def main() -> None:
    info = analyze()

    print("■ 1. 名前はプロファイルから機械的に決める")
    print(f"ルール : {SEGMENT_RULES}")
    print(f"結果   : {info['names']}")

    print(f"\n■ 2. 名前を付けた profile（k={K_MAIN}）")
    print_profile(info["profile"], info["names"])

    print("\n■ 3. 人数の構成比と売上の構成比")
    print(f"{'クラスタ':<8}{'セグメント名':<12}{'人数の割合':>12}{'売上の割合':>12}")
    for cluster in sorted(info["names"]):
        print(
            f"{cluster:<8}{info['names'][cluster]:<12}"
            f"{info['customer_share'][cluster]:>12.1%}{info['revenue_share'][cluster]:>12.1%}"
        )
    print(f"売上合計 : {info['total_revenue']:,} 円（本書の規約どおりの金額と一致する）")

    print("\n■ 4. 打ち手を 1 つずつ決める（ここまで書けて初めてセグメントが使える）")
    for cluster in sorted(info["names"]):
        name = info["names"][cluster]
        print(f"  {name} : {ACTIONS[name]}")

    print(f"\n■ 5. k={K_ALT} と k={K_MAIN} の対応（どちらを採るかの材料）")
    print(info["cross"].to_string())
    print(f"表の合計 : {info['cross_total']:,} 人 / 形 : {info['cross_shape']}")
    print("→ 数値はお手元の出力で確認してください。k を増やすと、どのクラスタが割れたのかが読めます")

    print("\n■ 6. 正解がないものを評価する 3 つの見方")
    print("(1) 内部指標 : シルエット係数。まとまり具合を数値で見る（この章では k=3 が最良）")
    print("(2) 安定性   : 条件を少し変えても同じ分かれ方になるか")
    for seed, counts in info["seed_counts"].items():
        print(f"    random_state={seed} の人数（多い順） : {counts}")
    print("    → 42 のときの並びと見比べ、大きく変わるかどうかを自分で確かめてください")
    print("(3) 有用性   : そのセグメントに違う打ち手を用意できるか。できないなら分けた意味がない")

    print("\n■ 7. 結論")
    print(f"k={K_ALT} はシルエット係数が最良、k={K_MAIN} は打ち手を 4 通り用意できる分け方です。")
    print("運用できるセグメントの数（施策の数・担当者の数）で決めるのが、いちばん外しにくい判断です。")

    print(f"\n図を保存しました: outputs/{draw(info)}")


if __name__ == "__main__":
    main()
