"""k-means で顧客を 4 つに分け、クラスタ profile を読む。

使い方:
    docker compose exec lab python src/session27/kmeans_basics.py
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from common import (
    FEATURES,
    K_MAIN,
    N_INIT,
    RANDOM_STATE,
    SILHOUETTE_SAMPLE,
    cluster_counts,
    fit_kmeans,
    print_profile,
    profile,
    rfm_table,
    scaled_matrix,
    segment_names,
)

# クラスタ中心と profile の平均が「一致している」とみなす相対誤差の上限
CENTER_TOL = 0.01


def analyze(k: int = K_MAIN) -> dict:
    """k-means の結果と、中心が profile の平均と一致することを確かめる。"""
    X = scaled_matrix()
    model = fit_kmeans(X, k)
    table = profile(k)

    # クラスタ中心は標準化された単位なので、元の単位（日・回・円）に戻して読む
    scaler = StandardScaler().fit(rfm_table())
    centers = scaler.inverse_transform(model.cluster_centers_)
    # 一致の確認は相対誤差で行う。KMeans は中心の移動量が tol（既定 1e-4）を下回ると
    # 反復を止めるので、中心は平均に「収束の許容誤差ぶん」だけ近い値で確定する。
    # 金額（数万円）の列を絶対値で比べると、正しい実装でも「不一致」に見えてしまう。
    values = table[FEATURES].to_numpy()
    gap = float((np.abs(centers - values) / np.abs(values)).max())

    return {
        "shape": X.shape,
        # 標準化できているか（平均はほぼ 0・標準偏差はちょうど 1 になる）
        "mean_abs_max": float(np.abs(X.mean(axis=0)).max()),
        "stds": [float(value) for value in X.std(axis=0)],
        "counts": cluster_counts(k),
        "total": int(sum(cluster_counts(k))),
        "inertia": float(model.inertia_),
        "silhouette": float(
            silhouette_score(X, model.labels_, sample_size=SILHOUETTE_SAMPLE, random_state=RANDOM_STATE)
        ),
        "profile": table,
        "names": segment_names(k),
        "centers_gap_relative": gap,                      # 実測 0.0018（0.18%）
        "centers_match_profile": bool(gap < CENTER_TOL),  # 相対 1% 未満なら「一致」とみなす
    }


def main() -> None:
    info = analyze()

    print("■ 1. 渡す行列（標準化した 3 指標）")
    print(f"形 : {info['shape']}（顧客 7,629 人 × 3 指標）")
    print(f"各列の平均の絶対値の最大 : {info['mean_abs_max']:.6f}")
    print(f"各列の標準偏差 : {' / '.join(f'{value:.3f}' for value in info['stds'])}")
    print("→ 単位（日・回・円）の違いが消え、3 指標が同じ重さで距離に効くようになった")

    print(f"\n■ 2. k-means を 1 回学習する（n_clusters={K_MAIN}・random_state={RANDOM_STATE}・n_init={N_INIT}）")
    print(f"inertia（中心までの距離の二乗の合計） : {info['inertia']:,.1f}")
    print(f"シルエット係数（sample_size={SILHOUETTE_SAMPLE}） : {info['silhouette']:.4f}")

    print("\n■ 3. クラスタごとの人数")
    for cluster, count in enumerate(info["counts"]):
        print(f"  クラスタ{cluster} : {count:>6,} 人")
    print(f"  合計       : {info['total']:>6,} 人（母集団と一致する）")

    print("\n■ 4. クラスタ profile（人数と 3 指標の平均）")
    print_profile(info["profile"], info["names"])
    print(
        f"クラスタ中心（元の単位に戻したもの）が profile の平均と一致するか : "
        f"{info['centers_match_profile']}（相対誤差の最大 {info['centers_gap_relative']:.2%}）"
    )
    print("→ k-means の中心は『そのクラスタの平均』そのもの。profile は中心を読みやすくした表")
    print(f"→ ぴったり 0 にならないのは、中心の移動が tol を下回った時点で反復を止めるため（相対 {CENTER_TOL:.0%} 未満なら一致とみなす）")


if __name__ == "__main__":
    main()
