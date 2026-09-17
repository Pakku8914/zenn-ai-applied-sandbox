"""問題2: k=4 でクラスタを作り、profile を読んでセグメント名を付ける。

使い方:
    docker compose exec lab python src/session27/q2_kmeans_profile.py
"""

from __future__ import annotations

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from common import (
    K_MAIN,
    N_INIT,
    RANDOM_STATE,
    SILHOUETTE_SAMPLE,
    print_profile,
    rfm_table,
    segment_names,
)


def analyze(k: int = K_MAIN) -> dict:
    """標準化 → k-means → profile までを 1 本の流れで書く。"""
    table = rfm_table()
    X = StandardScaler().fit_transform(table)  # 距離を使うので必ず先に標準化する
    model = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=N_INIT).fit(X)

    labeled = table.assign(cluster=model.labels_)
    summary = labeled.groupby("cluster").agg(
        n=("frequency", "size"),
        recency=("recency", "mean"),
        frequency=("frequency", "mean"),
        monetary=("monetary", "mean"),
    )
    return {
        "counts": np.bincount(model.labels_, minlength=k).tolist(),
        "total": int(len(table)),
        "inertia": float(model.inertia_),
        "silhouette": float(
            silhouette_score(X, model.labels_, sample_size=SILHOUETTE_SAMPLE, random_state=RANDOM_STATE)
        ),
        "profile": summary,
        "names": segment_names(k),
        "largest": int(summary["n"].idxmax()),
        "richest": int(summary["monetary"].idxmax()),
        "oldest": int(summary["recency"].idxmax()),
    }


def main() -> None:
    info = analyze()

    print(f"■ 1. クラスタごとの人数（k={K_MAIN}）")
    for cluster, count in enumerate(info["counts"]):
        print(f"  クラスタ{cluster} : {count:>6,} 人")
    print(f"  合計       : {info['total']:>6,} 人")

    print("\n■ 2. まとまり具合の指標")
    print(f"inertia          : {info['inertia']:,.1f}")
    print(f"シルエット係数   : {info['silhouette']:.4f}")

    print("\n■ 3. クラスタ profile とセグメント名")
    print_profile(info["profile"], info["names"])

    print("\n■ 4. 読み取り")
    print(f"人数が最も多いクラスタ       : {info['largest']}（ボリューム層）")
    print(f"1 人あたり売上が最も高いクラスタ : {info['richest']}（優良顧客）")
    print(f"最終購入がいちばん前のクラスタ  : {info['oldest']}（離脱顧客）")

    print("\n■ 5. 名前を付けるときの注意")
    print("『優良』『離脱』という名前は、数値ではなく人が与えた解釈です。")
    print("名前を付けた瞬間に『この人たちはこうだ』という思い込みが混ざるので、")
    print("名前と一緒に必ず profile の数値を添えて報告します。")


if __name__ == "__main__":
    main()
