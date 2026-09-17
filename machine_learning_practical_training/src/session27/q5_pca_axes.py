"""問題5: 主成分分析で 3 指標を 2 軸に圧縮し、寄与率と係数から軸の意味を読む。

使い方:
    docker compose exec lab python src/session27/q5_pca_axes.py
"""

from __future__ import annotations

import matplotlib
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import FEATURES, K_MAIN, RANDOM_STATE, fix_signs, labels_for, save_figure, scaled_matrix

FIGURE_NAME = "s27_q5_pca.png"


def analyze() -> dict:
    """PCA を自分で当てて、符号をそろえてから係数を読む。"""
    X = scaled_matrix()
    pca = PCA(n_components=len(FEATURES), random_state=RANDOM_STATE).fit(X)
    components = fix_signs(pca.components_)  # 向きをそろえてから読む
    coords = (X - pca.mean_) @ components.T

    ratio = [float(value) for value in pca.explained_variance_ratio_]
    table = pd.DataFrame(components, columns=FEATURES, index=[f"PC{i + 1}" for i in range(len(FEATURES))])
    return {
        "ratio": ratio,
        "cumulative": [float(value) for value in np.cumsum(ratio)],
        "ratio_sum": float(sum(ratio)),
        "loadings": table,
        "pc1_top": str(table.loc["PC1"].abs().idxmax()),
        "pc2_top": str(table.loc["PC2"].abs().idxmax()),
        "pc1_signs": {name: ("正" if table.loc["PC1", name] > 0 else "負") for name in FEATURES},
        "dot": float(components[0] @ components[1]),
        "norms": [float(np.linalg.norm(row)) for row in components],
        "coords_shape": coords.shape,
        "coords": coords,
    }


def draw(info: dict) -> str:
    """第 1・第 2 主成分の平面にクラスタを描き、軸の意味を表題に書く。"""
    coords = info["coords"]
    labels = np.asarray(labels_for(K_MAIN))
    colors = ["#4c78a8", "#f58518", "#54a24b", "#e45756"]
    fig, ax = plt.subplots(figsize=(7.2, 5.4))
    for cluster in range(K_MAIN):
        mask = labels == cluster
        ax.scatter(
            coords[mask, 0], coords[mask, 1], s=8, alpha=0.5,
            color=colors[cluster % len(colors)], label=f"クラスタ{cluster}（{int(mask.sum()):,} 人）",
        )
    ax.set_xlabel(f"第 1 主成分（寄与率 {info['ratio'][0]:.1%}）：買っている量")
    ax.set_ylabel(f"第 2 主成分（寄与率 {info['ratio'][1]:.1%}）：どれだけ前に買ったか")
    ax.set_title(f"累積寄与率 {info['cumulative'][1]:.2%} の 2 軸で顧客を見る")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    save_figure(fig, FIGURE_NAME)
    plt.close(fig)
    return FIGURE_NAME


def main() -> None:
    info = analyze()

    print("■ 1. 寄与率と累積寄与率")
    for index, (ratio, cumulative) in enumerate(zip(info["ratio"], info["cumulative"]), start=1):
        print(f"  PC{index} : 寄与率 {ratio:.4f} / 累積 {cumulative:.4f}")
    print(f"寄与率の合計 : {info['ratio_sum']:.4f}（3 軸すべて使えば情報は失われない）")

    print("\n■ 2. 主成分の係数（第 1・第 2 のみ）")
    print(f"{'':<6}{'recency':>10}{'frequency':>11}{'monetary':>10}")
    for name in ("PC1", "PC2"):
        row = info["loadings"].loc[name]
        print(f"{name:<6}{row['recency']:>+10.4f}{row['frequency']:>+11.4f}{row['monetary']:>+10.4f}")

    print("\n■ 3. 軸の意味")
    print(f"PC1 で最も強い指標 : {info['pc1_top']}（符号の向き : {info['pc1_signs']}）")
    print("→ frequency と monetary が正、recency が負。「よく買っている」ほど右にくる軸")
    print(f"PC2 で最も強い指標 : {info['pc2_top']}")
    print("→ recency がほぼ単独で効く。「最後に買ってからどれだけ経ったか」の軸")

    print("\n■ 4. 符号の正規化と確認")
    print("主成分の向きは反転しうるので、絶対値が最大の係数が正になるようにそろえています。")
    # ごく小さな負の値（-0.0000001 など）が -0.000000 と表示されないように丸めてから足す
    print(f"PC1 と PC2 の内積 : {round(info['dot'], 6) + 0.0:.6f}（0 なら直交）")
    print(f"係数ベクトルの長さ : {' / '.join(f'{value:.4f}' for value in info['norms'])}")

    print(f"\n■ 5. 圧縮後の座標の形 : {info['coords_shape']}")
    print("2 軸だけを使えば (7629, 2) になり、散布図 1 枚で全顧客を見渡せます。")

    print(f"\n図を保存しました: outputs/{draw(info)}")


if __name__ == "__main__":
    main()
