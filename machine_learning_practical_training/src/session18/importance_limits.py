"""特徴量重要度を「浅い木」と「フォレスト」で比べ、順位が入れ替わることを確かめる。

使い方:
    docker compose exec lab python src/session18/importance_limits.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    OUT_DIR,
    SHOWCASE_DEPTH,
    importance_table,
    load_review_table,
    make_forest,
    make_tree,
    pad,
    pipeline_for,
    split_xy,
)

# セッション16 で statsmodels が出した published_year の p 値（有意でないと判定された）
PUBLISHED_YEAR_PVALUE = 0.2425


def compare_table(tree_table, forest_table):
    """2 つの重要度を突き合わせ、木の重要度が大きい順に並べた表を返す。"""
    merged = tree_table.merge(forest_table, on="feature", suffixes=("_tree", "_forest"))
    merged = merged.sort_values(
        ["importance_tree", "importance_forest"], ascending=False
    ).reset_index(drop=True)
    merged["rank_forest"] = (
        merged["importance_forest"].rank(ascending=False, method="min").astype("int64")
    )
    used = merged.loc[merged["importance_tree"] > 0, "importance_tree"]
    tree_ranks = used.rank(ascending=False, method="min").astype("int64")
    merged["rank_tree"] = [
        f"{tree_ranks.loc[i]} 位" if i in tree_ranks.index else "使われず" for i in merged.index
    ]
    return merged


def plot_importances(merged, path, depth: int) -> None:
    """2 つのモデルの重要度を横棒で並べて描く（同じ列を同じ高さにそろえる）。"""
    fig, ax = plt.subplots(figsize=(8.4, 5.0))
    positions = range(len(merged))
    offsets = [p + 0.2 for p in positions]
    shifted = [p - 0.2 for p in positions]
    ax.barh(shifted, merged["importance_tree"], height=0.38, color="#4c78a8", label=f"決定木（深さ {depth}）")
    ax.barh(offsets, merged["importance_forest"], height=0.38, color="#54a24b", label="ランダムフォレスト")
    ax.set_yticks(list(positions))
    ax.set_yticklabels(merged["feature"])
    ax.invert_yaxis()
    ax.set_xlabel("特徴量重要度（合計が 1 になるように割った値）")
    ax.set_title("同じデータでもモデルが変わると重要度の順位は変わる")
    ax.legend(loc="lower right")
    fig.tight_layout()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main() -> None:
    X_train, X_test, y_train, y_test = split_xy(load_review_table())
    tree_pipeline = pipeline_for(make_tree(SHOWCASE_DEPTH)).fit(X_train, y_train)
    forest_pipeline = pipeline_for(make_forest()).fit(X_train, y_train)
    merged = compare_table(importance_table(tree_pipeline), importance_table(forest_pipeline))

    print(f"■ 特徴量重要度を 2 つのモデルで比べる（合計は必ず 1 になる / 訓練 {len(X_train):,} 件）")
    print(f"{pad('特徴量', 18)}| 決定木（深さ {SHOWCASE_DEPTH}） | フォレスト | 順位の動き")
    for row in merged.itertuples(index=False):
        print(
            f"{pad(row.feature, 18)}|{row.importance_tree:>17.4f} |"
            f"{row.importance_forest:>11.4f} | {row.rank_tree} → {row.rank_forest} 位"
        )
    print(
        f"{pad('合計', 18)}|{merged['importance_tree'].sum():>17.4f} |"
        f"{merged['importance_forest'].sum():>11.4f} |"
    )
    print()

    zeros = merged.loc[merged["importance_tree"] == 0]
    print("■ 「浅い木では 0、フォレストでは 0 でない」列")
    for row in zeros.head(2).itertuples(index=False):
        print(
            f"{pad(row.feature, 16)}: {row.importance_tree:.4f} → {row.importance_forest:.4f}"
            f"（フォレストでは {row.rank_forest} 位）"
        )
    print(f"同じように 0 でなくなった列は全部で {len(zeros)} 列あります")
    print()

    year = merged.loc[merged["feature"] == "published_year"].iloc[0]
    print("■ 重要度が 0 でないことは「効いている」証拠にならない")
    print(f"published_year のフォレストの重要度        : {year.importance_forest:.4f}")
    print(f"published_year の statsmodels の p 値（S16）: {PUBLISHED_YEAR_PVALUE:.4f}")
    print("→ 重要度は 4 番目に大きいのに、統計的には「有意でない」と判定された列です。")
    print("  重要度は『木がその列で何回・どれだけ不純度を下げたか』の記録にすぎません。")
    print()

    plot_importances(merged, OUT_DIR / "s18_importance.png", SHOWCASE_DEPTH)
    print("図を保存しました: outputs/s18_importance.png")


if __name__ == "__main__":
    main()
