"""浅い決定木（深さ 3）の中身を図にして、どの列が分岐に使われたかを確かめる。

使い方:
    docker compose exec lab python src/session18/plot_shallow_tree.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.tree import plot_tree

from common import (
    OUT_DIR,
    SHOWCASE_DEPTH,
    feature_names,
    importance_table,
    load_review_table,
    make_tree,
    pipeline_for,
    raw_feature_names,
    split_xy,
)

# 図の中で使う分類の名前（tree.classes_ が [0 1] なので この順番にそろえる）
CLASS_NAMES = ["低評価", "高評価"]


def draw_tree(pipeline, path, depth: int) -> None:
    """plot_tree で木の形をそのまま描く。

    列名は前処理後の名前（num__unit_price など）をそのまま渡します。
    閾値は**標準化後の目盛**（平均 0・1 標準偏差 = 1）で表示される点に注意してください。
    """
    fig, ax = plt.subplots(figsize=(17, 8))
    plot_tree(
        pipeline.named_steps["model"],
        feature_names=raw_feature_names(pipeline),
        class_names=CLASS_NAMES,
        filled=True,
        rounded=True,
        impurity=True,  # 各ノードのジニ係数を表示する（1 節で手計算したもの）
        fontsize=8,
        ax=ax,
    )
    ax.set_title(f"決定木（深さ {depth}）― 四角 1 つが 1 つの質問、末端が葉")
    fig.tight_layout()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main() -> None:
    X_train, X_test, y_train, y_test = split_xy(load_review_table())
    pipeline = pipeline_for(make_tree(SHOWCASE_DEPTH)).fit(X_train, y_train)
    tree = pipeline.named_steps["model"]
    table = importance_table(pipeline)

    used = table.loc[table["importance"] > 0].sort_values("importance", ascending=False)
    unused = table.loc[table["importance"] == 0]

    print(f"■ 浅い木（深さ {SHOWCASE_DEPTH}）の中身")
    print(f"葉の数 {tree.get_n_leaves()} 枚 / ノード {tree.tree_.node_count} 個 / 特徴量 {len(feature_names(pipeline))} 列")
    print(f"分岐に使われた列（{len(used)} 列）: {', '.join(used['feature'])}")
    print(f"使われなかった列（{len(unused)} 列）: {', '.join(unused['feature'])}")
    print()

    # 「使われた列」を木の中身から数えても同じになることを確認する
    used_from_tree = {feature_names(pipeline)[i] for i in tree.tree_.feature if i >= 0}
    print("■ 木の中身（tree_.feature）から数えた結果と一致するか")
    print(f"重要度が 0 でない列と一致したか: {used_from_tree == set(used['feature'])}")
    print()

    draw_tree(pipeline, OUT_DIR / "s18_tree.png", SHOWCASE_DEPTH)
    print("図を保存しました: outputs/s18_tree.png")
    print("※ 図の閾値は標準化後の目盛です（平均 0・1 標準偏差 = 1）。円や文字数ではありません。")


if __name__ == "__main__":
    main()
