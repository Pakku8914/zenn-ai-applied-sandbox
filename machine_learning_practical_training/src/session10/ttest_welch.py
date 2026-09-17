"""カテゴリ別の rating を要約し、2 群の平均の差を Welch の t 検定で確かめる。

使い方:
    docker compose exec lab python src/session10/ttest_welch.py
"""

from __future__ import annotations

from common import ALPHA, load_reviews, print_result, ratings_by_category, welch_test


def main() -> None:
    df = load_reviews()
    groups = ratings_by_category(df)

    print(f"■ カテゴリ別の rating（欠損を除いた {len(df):,} 件）")
    print("カテゴリ | 件数 | 平均 | 標準偏差")
    for name in sorted(groups, key=lambda c: -groups[c].mean()):
        s = groups[name]
        print(f"{name} | {len(s):,} | {s.mean():.4f} | {s.std(ddof=1):.4f}")

    print()
    print("帰無仮説  H0: 技術書と小説の rating の平均は等しい")
    print("対立仮説  H1: 技術書と小説の rating の平均は等しくない")
    print(f"有意水準  α = {ALPHA}（データを見る前に決めておく）")
    print()

    result = welch_test(groups["技術書"], groups["小説"])
    print_result("技術書 vs 小説（Welch の t 検定）", result)

    print()
    if result["p"] < ALPHA:
        print("判定: 帰無仮説を捨てる（平均が等しいとは考えにくい）")
    else:
        print("判定: 帰無仮説を捨てられない（平均が違うとは言えない）")
    print("報告に必要なのは p 値だけではありません。平均差・信頼区間・効果量をそろえて書きます。")


if __name__ == "__main__":
    main()
