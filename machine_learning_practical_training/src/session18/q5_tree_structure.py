"""問題5 の解答: 浅い木の形（葉・ノード・使われた列）を数えて、図に描く。

使い方:
    docker compose exec lab python src/session18/q5_tree_structure.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.tree import plot_tree

from common import (
    OUT_DIR,
    feature_names,
    importance_table,
    load_review_table,
    make_tree,
    pipeline_for,
    raw_feature_names,
    split_xy,
)

DEPTHS_TO_COUNT = [2, 3]
FIGURE_DEPTH = 2  # 図にする深さ（浅いほど文字が読める）
CLASS_NAMES = ["低評価", "高評価"]


def structure_of(pipeline) -> dict:
    """学習済みの木から、葉の数・ノードの数・分岐の数を取り出す。"""
    inner = pipeline.named_steps["model"].tree_
    leaves = int(pipeline.named_steps["model"].get_n_leaves())
    return {
        "leaves": leaves,
        "nodes": int(inner.node_count),
        "splits": int(inner.node_count) - leaves,
    }


def main() -> None:
    X_train, X_test, y_train, y_test = split_xy(load_review_table())
    print("■ 問題5: 木の形を数える")
    pipelines = {}
    for depth in DEPTHS_TO_COUNT:
        pipeline = pipeline_for(make_tree(depth)).fit(X_train, y_train)
        pipelines[depth] = pipeline
        shape = structure_of(pipeline)
        print(
            f"深さ {depth} : 葉 {shape['leaves']} 枚 / ノード {shape['nodes']} 個 / 分岐 {shape['splits']} 個 / "
            f"ノード = 葉 × 2 - 1 が成り立つか: {shape['nodes'] == shape['leaves'] * 2 - 1}"
        )
    print()

    deepest = pipelines[max(DEPTHS_TO_COUNT)]
    table = importance_table(deepest)
    used = table.loc[table["importance"] > 0].sort_values("importance", ascending=False)
    unused = table.loc[table["importance"] == 0]
    print(f"■ 深さ {max(DEPTHS_TO_COUNT)} の木が使った列（全 {len(feature_names(deepest))} 列のうち）")
    print(f"使った列（{len(used)} 列）    : {', '.join(used['feature'])}")
    print(f"使わなかった列（{len(unused)} 列）: {', '.join(unused['feature'])}")
    print()

    target = pipelines[FIGURE_DEPTH]
    fig, ax = plt.subplots(figsize=(13, 6))
    plot_tree(
        target.named_steps["model"],
        feature_names=raw_feature_names(target),
        class_names=CLASS_NAMES,
        filled=True,
        rounded=True,
        fontsize=9,
        ax=ax,
    )
    ax.set_title(f"決定木（深さ {FIGURE_DEPTH}）の分岐 ― 閾値は標準化後の目盛")
    fig.tight_layout()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_DIR / "s18_q5_tree.png", dpi=100)
    plt.close(fig)
    print("図を保存しました: outputs/s18_q5_tree.png")
    print("※ 図の閾値は標準化後の値です。円や文字数に戻すには StandardScaler の mean_ と scale_ を使います。")


if __name__ == "__main__":
    main()
