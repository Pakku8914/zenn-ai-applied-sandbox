"""主成分分析で 3 指標を 2 つの軸に圧縮し、寄与率と係数から軸の意味を読む。

使い方:
    docker compose exec lab python src/session27/pca_axes.py
"""

from __future__ import annotations

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import FEATURES, K_MAIN, labels_for, loadings, pca_bundle, save_figure, segment_names

FIGURE_NAME = "s27_pca_clusters.png"
READ_COMPONENTS = 2  # 読むのは第 1・第 2 主成分だけ（第 3 は寄与率が小さい）


def analyze() -> dict:
    """寄与率・累積寄与率・主成分の係数と、直交性の確認をまとめて返す。"""
    bundle = pca_bundle()
    table = loadings()
    components = bundle["components"]
    return {
        "ratio": bundle["ratio"],
        "cumulative": bundle["cumulative"],
        "loadings": table,
        "norms": [float(np.linalg.norm(row)) for row in components],
        "dot_pc1_pc2": float(components[0] @ components[1]),
        "coords_shape": bundle["coords"].shape,
        # 符号をそろえる規則が効いているか（各主成分で影響が最大の係数が正になる）
        "top_features": [FEATURES[int(np.abs(row).argmax())] for row in components],
        "top_is_positive": bool(all(row[int(np.abs(row).argmax())] > 0 for row in components)),
    }


def draw(info: dict) -> str:
    """第 1・第 2 主成分の平面に、k-means のクラスタを色分けして描く。"""
    bundle = pca_bundle()
    coords = bundle["coords"]
    labels = np.asarray(labels_for(K_MAIN))
    names = segment_names(K_MAIN)
    colors = ["#4c78a8", "#f58518", "#54a24b", "#e45756", "#b279a2"]

    fig, ax = plt.subplots(figsize=(7.2, 5.4))
    for cluster in sorted(names):
        mask = labels == cluster
        ax.scatter(
            coords[mask, 0],
            coords[mask, 1],
            s=8,
            alpha=0.5,
            color=colors[cluster % len(colors)],
            label=f"クラスタ{cluster}：{names[cluster]}（{int(mask.sum()):,} 人）",
        )
    ax.set_xlabel(f"第 1 主成分（寄与率 {info['ratio'][0]:.1%}）：買っている量")
    ax.set_ylabel(f"第 2 主成分（寄与率 {info['ratio'][1]:.1%}）：どれだけ前に買ったか")
    ax.set_title(f"3 指標を 2 つの軸に圧縮して見る（累積寄与率 {info['cumulative'][1]:.2%}）")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    save_figure(fig, FIGURE_NAME)
    plt.close(fig)
    return FIGURE_NAME


def main() -> None:
    info = analyze()

    print("■ 1. 寄与率（それぞれの軸が元の情報の何割を持っているか）")
    for index, (ratio, cumulative) in enumerate(zip(info["ratio"], info["cumulative"]), start=1):
        print(f"  第 {index} 主成分 : 寄与率 {ratio:.4f}（{ratio:.2%}） / 累積 {cumulative:.4f}")
    print(f"→ 第 1・第 2 主成分だけで元の情報の {info['cumulative'][1]:.2%} を保てる")

    print("\n■ 2. 主成分の係数（元の 3 指標をどう混ぜた軸か）")
    print(f"{'':<6}{'recency':>10}{'frequency':>11}{'monetary':>10}")
    for name, row in info["loadings"].head(READ_COMPONENTS).iterrows():
        print(f"{name:<6}{row['recency']:>+10.4f}{row['frequency']:>+11.4f}{row['monetary']:>+10.4f}")
    print("第 3 主成分は寄与率が小さいので読みません（無理に意味づけしない）")

    print("\n■ 3. 軸の意味を読む")
    print("第 1 主成分 : frequency と monetary が大きな正・recency が負 → 「買っている量」の軸")
    print("第 2 主成分 : recency がほぼ 1 に近い正 → 「どれだけ前に買ったか」の軸")

    print("\n■ 4. 符号は反転しうるので、読む前に向きをそろえる")
    print(f"各主成分で影響が最大の指標 : {info['top_features']}")
    print(f"その係数が正になっているか : {info['top_is_positive']}")
    # ごく小さな負の値が -0.000000 と表示されないように丸めてから足す
    print(f"第 1 主成分と第 2 主成分の内積（直交しているか） : {round(info['dot_pc1_pc2'], 6) + 0.0:.6f}")
    print(f"係数ベクトルの長さ : {' / '.join(f'{value:.4f}' for value in info['norms'])}")

    print(f"\n■ 5. 圧縮した座標の形 : {info['coords_shape']}（7,629 人 × 3 軸）")
    print("PCA はクラスタを作りません。軸を取り直して『見やすくする』だけの道具です。")

    print(f"\n図を保存しました: outputs/{draw(info)}")
    print("図から読めること : 右にいくほどよく買っている人、上にいくほど長く買っていない人")


if __name__ == "__main__":
    main()
