"""課題7（発展）：カテゴリ別の平均評価を検定し、効果量と信頼区間つきで報告する。

    docker compose exec lab python src/mid01/rating_test.py

「売れているカテゴリ」と「高く評価されているカテゴリ」は同じではない、という補足の
分析です。p 値だけを書かず、平均差・95% 信頼区間・効果量を必ず並べます
（セッション 10 の報告の作法）。検定の道具は common.py の配布コードを使います。
"""

from __future__ import annotations

import pandas as pd

from common import ALPHA, format_p, load_rated_reviews, welch_test

# 3 通りの結果（はっきり差がある / 有意だが小さい / 有意でない）が出るように選んだ組
PAIRS = [("技術書", "小説"), ("小説", "児童書"), ("技術書", "ビジネス")]


def rating_summary(rated: pd.DataFrame) -> pd.DataFrame:
    """カテゴリ別の件数と平均評価（平均の高い順）。"""
    summary = rated.groupby("category", observed=True).agg(
        reviews=("rating", "count"), mean_rating=("rating", "mean")
    )
    return summary.sort_values("mean_rating", ascending=False)


def main() -> None:
    rated = load_rated_reviews()
    summary = rating_summary(rated)
    print(f"■ カテゴリ別の平均評価（星が入っているレビュー {summary['reviews'].sum():,.0f} 件）")
    for name, row in summary.iterrows():
        print(f"  {name}: {row['reviews']:,.0f} 件 / 平均 {row['mean_rating']:.4f}")

    print(f"\n■ Welch の t 検定（有意水準 {ALPHA}）")
    for left, right in PAIRS:
        result = welch_test(
            rated.loc[rated["category"] == left, "rating"],
            rated.loc[rated["category"] == right, "rating"],
        )
        crosses_zero = result["ci_low"] < 0 < result["ci_high"]
        verdict = "有意ではない" if result["p"] >= ALPHA else "有意"
        print(f"  {left} vs {right}")
        print(f"    件数     : {result['n1']:,} 件 vs {result['n2']:,} 件")
        print(f"    平均差   : {result['diff']:+.4f}")
        print(
            f"    95%CI    : [{result['ci_low']:+.4f}, {result['ci_high']:+.4f}]"
            + ("（0 をまたぐ）" if crosses_zero else "")
        )
        print(f"    効果量 d : {result['d']:+.4f}")
        print(f"    p 値     : {format_p(result['p'])} → {verdict}")


if __name__ == "__main__":
    main()
