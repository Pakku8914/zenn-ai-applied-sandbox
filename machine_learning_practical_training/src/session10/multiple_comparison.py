"""5 カテゴリの全 10 ペアを検定し、多重比較と Bonferroni 補正の効き方を確かめる。

図 outputs/s10_effect_size.png も保存します。

使い方:
    docker compose exec lab python src/session10/multiple_comparison.py
"""

from __future__ import annotations

from itertools import combinations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import ALPHA, CATEGORIES, OUT_DIR, load_reviews, ratings_by_category, welch_test


def main() -> None:
    groups = ratings_by_category(load_reviews())

    # 比較するペアは「データを見る前に」全 10 通りと決めておく（都合のよいペアだけ選ばない）
    pairs = list(combinations(CATEGORIES, 2))
    results = [(a, b, welch_test(groups[a], groups[b])) for a, b in pairs]
    alpha_bonferroni = ALPHA / len(pairs)

    print(f"■ {len(CATEGORIES)} カテゴリの全 {len(pairs)} ペアを Welch の t 検定にかける")
    print(f"ペア | 平均差 | p 値 | Cohen's d | α={ALPHA} | α={alpha_bonferroni}")
    for a, b, r in results:
        mark = "有意" if r["p"] < ALPHA else "-"
        mark_b = "有意" if r["p"] < alpha_bonferroni else "-"
        print(f"{a} vs {b} | {r['diff']:+.4f} | {r['p']:.1e} | {r['d']:+.4f} | {mark} | {mark_b}")

    before = sum(1 for _, _, r in results if r["p"] < ALPHA)
    after = sum(1 for _, _, r in results if r["p"] < alpha_bonferroni)
    familywise = 1 - (1 - ALPHA) ** len(pairs)

    print()
    print("■ 多重比較")
    print(f"  検定の回数: {len(pairs)}")
    print(f"  どれか 1 つでも偶然 p < {ALPHA} になる確率: 1 - 0.95^{len(pairs)} = {familywise:.1%}")
    print(f"  α = {ALPHA} で有意: {before} / {len(pairs)} ペア")
    print(f"  Bonferroni 補正後（α = {alpha_bonferroni}）で有意: {after} / {len(pairs)} ペア")
    if before == after:
        print("  → このデータでは、補正しても結論は 1 つも変わりませんでした")
    else:
        print(f"  → 補正によって {before - after} ペアが有意でなくなりました")

    OUT_DIR.mkdir(exist_ok=True)
    ordered = sorted(results, key=lambda row: abs(row[2]["d"]))
    labels = [f"{a} vs {b}" for a, b, _ in ordered]
    values = [abs(r["d"]) for _, _, r in ordered]
    colors = ["#4c78a8" if r["p"] < alpha_bonferroni else "#bab0ac" for _, _, r in ordered]
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    ax.barh(labels, values, color=colors)
    for x in (0.2, 0.5, 0.8):
        ax.axvline(x, color="#888888", linestyle="--", linewidth=0.8)
    ax.set_xlabel("効果量の大きさ |Cohen's d|（破線は左から 小 0.2・中 0.5・大 0.8 の目安）")
    ax.set_title("10 ペアの効果量（青 = Bonferroni 補正後も有意）")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "s10_effect_size.png", dpi=120)
    plt.close(fig)
    print("\n図を保存しました: outputs/s10_effect_size.png")


if __name__ == "__main__":
    main()
