"""実装問題 9：検定結果の誤った報告文を、効果量と信頼区間を使って書き直す。

使い方:
    docker compose exec lab python src/review01/q9_report_fix.py
"""

from __future__ import annotations

from itertools import combinations

import pandas as pd
from scipy import stats

from common import (
    ALPHA,
    CATEGORIES,
    cramers_v,
    format_p,
    load_orders_with_customer,
    load_rated_reviews,
    welch_test,
)


def show(number: int, wrong: str, facts: list[str], right: str) -> None:
    """誤った報告・根拠になる数値・書き直した報告を、この順で並べて表示する。"""
    print(f"■ 報告 {number}")
    print(f"  × 誤: {wrong}")
    for fact in facts:
        print(f"       {fact}")
    print(f"  ○ 正: {right}")
    print()


def report1_small_effect(groups: dict[str, pd.Series]) -> None:
    """p 値が小さいことを「差が大きい」と読み替えてしまう誤り（セッション 10）。"""
    small = welch_test(groups["小説"], groups["児童書"])
    big = welch_test(groups["技術書"], groups["小説"])
    show(
        1,
        "p < 0.001 なので、小説と児童書の評価には大きな差がある。",
        [
            f"小説 {small['n1']:,} 件 平均 {small['mean1']:.4f} / 児童書 {small['n2']:,} 件 平均 {small['mean2']:.4f}",
            f"p 値 {format_p(small['p'])} → α = {ALPHA} のもとで帰無仮説を捨てる",
            f"95% 信頼区間が 0 を含むか: {small['ci_low'] < 0 < small['ci_high']}",
            f"効果量 d = {small['d']:+.4f}（比較用：技術書 vs 小説 は d = {big['d']:+.4f}）",
        ],
        f"小説（{small['n1']:,} 件・平均 {small['mean1']:.4f}）と児童書（{small['n2']:,} 件・平均 "
        f"{small['mean2']:.4f}）の平均の差は星 {abs(small['diff']):.4f} 分で、信頼区間は 0 を含まず、"
        f"p 値は有意水準を下回りました。ただし効果量は d = {small['d']:+.4f} と小さく（|d| < 0.2）、"
        "読者が感じる違いとしてはごくわずかです。p 値が小さいのは差が大きいからではなく件数が多いからです。",
    )


def report2_not_significant(groups: dict[str, pd.Series]) -> None:
    """「有意でない」を「差がない」と言い換えてしまう誤り（セッション 10）。"""
    none = welch_test(groups["技術書"], groups["ビジネス"])
    show(
        2,
        "p = 0.1024 で有意ではなかったので、技術書とビジネスの評価に差はない。",
        [
            f"技術書 {none['n1']:,} 件 平均 {none['mean1']:.4f} / ビジネス {none['n2']:,} 件 平均 {none['mean2']:.4f}",
            f"p 値 {format_p(none['p'])} → α = {ALPHA} のもとで帰無仮説を捨てられない",
            f"95% 信頼区間が 0 を含むか: {none['ci_low'] < 0 < none['ci_high']}",
        ],
        f"技術書（{none['n1']:,} 件・平均 {none['mean1']:.4f}）とビジネス（{none['n2']:,} 件・平均 "
        f"{none['mean2']:.4f}）の比較では、有意水準 {ALPHA} のもとで帰無仮説を捨てられませんでした"
        f"（p = {format_p(none['p'])}）。95% 信頼区間は 0 をまたいでおり、差の向きさえ決まりません。"
        "言えるのは「今回のデータでは差があるとは言えない」までで、「差がない」ことを示したわけではありません。",
    )


def report3_chi_square() -> None:
    """関連の強さと因果を取り違える誤り（セッション 9・10）。"""
    orders = load_orders_with_customer()
    channel_table = pd.crosstab(orders["channel"], orders["is_canceled"])
    chi2, p_value, dof, _ = stats.chi2_contingency(channel_table)
    region_table = pd.crosstab(orders["region"], orders["is_canceled"])
    chi2_region, p_region, dof_region, _ = stats.chi2_contingency(region_table)
    v_channel = cramers_v(channel_table, float(chi2))
    region_total = int(region_table.to_numpy().sum())
    region_missing = int(orders["region"].isna().sum())
    show(
        3,
        "chi2 = 738.36、p = 1.009e-159 なので、流入チャネルがキャンセルの主な原因である。",
        [
            f"表の合計 {int(channel_table.to_numpy().sum()):,} 件（重複 30 件を除いた注文）",
            f"chi2 = {chi2:.4f} / 自由度 {dof} / p = {p_value:.3e}",
            f"Cramér's V = {v_channel:.4f} → 関連は弱い（0.2 未満）",
            f"地域では chi2 = {chi2_region:.4f} / 自由度 {dof_region} / p = {p_region:.3e} / "
            f"V = {cramers_v(region_table, float(chi2_region)):.4f}",
            f"地域の表の合計が注文 {len(orders):,} 件より小さいか: {region_total < len(orders)}"
            f"（落ちた行数が region 未入力の行数と一致するか: {len(orders) - region_total == region_missing}）",
        ],
        "流入チャネルとキャンセルの有無には関連が見られました（帰無仮説を捨てる）。"
        f"ただし関連の強さは Cramér's V = {v_channel:.4f} と弱く、検定が示すのは「無関係とは言いにくい」"
        "ことだけで、どちらが原因かは分かりません。なお地域の表は region が未入力の行を黙って落とすため、"
        "合計が注文件数より小さくなります。集計に使う前に必ず合計を検算します。",
    )


def report4_multiple_comparison(groups: dict[str, pd.Series]) -> None:
    """有意なペアの数を結論にしてしまう誤り（セッション 10）。"""
    pairs = list(combinations(CATEGORIES, 2))
    results = {pair: welch_test(groups[pair[0]], groups[pair[1]]) for pair in pairs}
    alpha_bonferroni = ALPHA / len(pairs)
    before = sum(1 for r in results.values() if r["p"] < ALPHA)
    after = sum(1 for r in results.values() if r["p"] < alpha_bonferroni)
    not_significant = [f"{x} vs {y}" for (x, y), r in results.items() if r["p"] >= ALPHA]
    significant_but_small = [
        f"{x} vs {y}" for (x, y), r in results.items() if r["p"] < ALPHA and abs(r["d"]) < 0.2
    ]
    show(
        4,
        "10 ペア中 9 ペアで p < 0.05 だったので、カテゴリによって評価は全面的に違う。",
        [
            f"ペア数 {len(pairs)} / どれか 1 つが偶然有意になる確率 {1 - (1 - ALPHA) ** len(pairs):.1%}",
            f"α = {ALPHA} で有意 {before} ペア / Bonferroni 補正後（α = {alpha_bonferroni:.3f}）も {after} ペア",
            f"有意でないペア: {not_significant}",
            f"有意だが効果量が小さい（|d| < 0.2）ペア: {significant_but_small}",
        ],
        f"5 カテゴリの総当たり {len(pairs)} ペアのうち {before} ペアが α = {ALPHA} で有意で、"
        f"Bonferroni 補正（α = {alpha_bonferroni:.3f}）後も {after} ペアが残りました。"
        "ただし「有意なペアの数」は結論ではありません。効果量で見ると "
        f"{'・'.join(significant_but_small)} は小さな差にとどまり、"
        f"{'・'.join(not_significant)} は差があるとは言えませんでした。"
        "報告ではペアごとに平均差・信頼区間・効果量を並べ、有意だったペアだけを抜き出しません。",
    )


def main() -> None:
    reviews = load_rated_reviews()
    groups = {name: reviews.loc[reviews["category"] == name, "rating"] for name in CATEGORIES}
    print(f"母集団: 星が入っているレビュー {len(reviews):,} 件（rating が未入力の行は除外）\n")
    report1_small_effect(groups)
    report2_not_significant(groups)
    report3_chi_square()
    report4_multiple_comparison(groups)


if __name__ == "__main__":
    main()
