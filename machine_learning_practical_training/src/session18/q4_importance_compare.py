"""問題4 の解答: 重要度を「浅い木」と「フォレスト」で比べ、順位の入れ替わりを見つける。

使い方:
    docker compose exec lab python src/session18/q4_importance_compare.py
"""

from __future__ import annotations

import pandas as pd

from common import (
    SHOWCASE_DEPTH,
    importance_table,
    load_review_table,
    make_forest,
    make_tree,
    pad,
    pipeline_for,
    split_xy,
)

TOP_N = 3
PUBLISHED_YEAR_PVALUE = 0.2425  # セッション16 で statsmodels が出した p 値
RANK_MOVE_LIMIT = 2  # 順位がこれ以上動いた列を「入れ替わった」とみなす


def ranked(table: pd.DataFrame) -> pd.DataFrame:
    """重要度の大きい順に順位を振る（同じ値なら小さい順位にそろえる）。"""
    out = table.copy()
    out["rank"] = out["importance"].rank(ascending=False, method="min").astype("int64")
    # kind="mergesort" は安定ソート。重要度が同じ列（0 が並ぶ）の順番が毎回同じになる
    return out.sort_values("importance", ascending=False, kind="mergesort").reset_index(drop=True)


def main() -> None:
    X_train, X_test, y_train, y_test = split_xy(load_review_table())
    tree = ranked(importance_table(pipeline_for(make_tree(SHOWCASE_DEPTH)).fit(X_train, y_train)))
    forest = ranked(importance_table(pipeline_for(make_forest()).fit(X_train, y_train)))

    print("■ 問題4: 重要度の比較")
    print(f"ランダムフォレストの重要度（上位 {TOP_N}）")
    top = forest.head(TOP_N)
    for row in top.itertuples(index=False):
        print(f"{row.rank} 位 {pad(row.feature, 16)}: {row.importance:.4f}")
    print(f"上位 1 列の占める割合 : {forest['importance'].iloc[0]:.4f}")
    print(f"上位 {TOP_N} 列の占める割合 : {top['importance'].sum():.4f}")
    print(f"重要度の合計（必ず 1 になる）: {forest['importance'].sum():.4f}")
    print()

    print(f"■ 決定木（深さ {SHOWCASE_DEPTH}）で重要度が 0 だった列")
    zeros = tree.loc[tree["importance"] == 0, "feature"].tolist()
    print(f"{len(zeros)} 列: {', '.join(zeros)}")
    print("→ 浅い木は 7 回しか分岐しないので、使われない列が残ります（0 は「関係がない」ではありません）")
    print()

    print("■ 両方のモデルで使われた列の順位の動き")
    both = tree.loc[tree["importance"] > 0, ["feature", "rank", "importance"]].merge(
        forest[["feature", "rank", "importance"]], on="feature", suffixes=("_tree", "_forest")
    )
    both["move"] = (both["rank_forest"] - both["rank_tree"]).abs()
    for row in both.itertuples(index=False):
        print(
            f"{pad(row.feature, 16)}: 木 {row.rank_tree} 位（{row.importance_tree:.4f}）"
            f" → フォレスト {row.rank_forest} 位（{row.importance_forest:.4f}）／動き {row.move}"
        )
    moved = both.loc[both["move"] >= RANK_MOVE_LIMIT, "feature"].tolist()
    print(f"順位が {RANK_MOVE_LIMIT} つ以上動いた列: {', '.join(moved) if moved else 'なし'}")
    print()

    print("■ 重要度だけで「効いている」と言えないことの確認")
    year = forest.loc[forest["feature"] == "published_year"].iloc[0]
    pages = forest.loc[forest["feature"] == "pages"].iloc[0]
    print(f"published_year : フォレストの重要度 {year.importance:.4f}（{year['rank']} 位）"
          f" / セッション16 の p 値 {PUBLISHED_YEAR_PVALUE:.4f}")
    tree_pages = tree.loc[tree["feature"] == "pages", "importance"].iloc[0]
    print(f"pages          : 浅い木では {tree_pages:.4f} / フォレストでは {pages.importance:.4f}"
          f"（{pages['rank']} 位）")
    print("→ 同じデータでも、モデルを変えるだけで重要度の順位は入れ替わります。")


if __name__ == "__main__":
    main()
