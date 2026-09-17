"""「有意だが小さい差」と「有意ではない」を並べ、効果量と信頼区間の役割を確かめる。

図 outputs/s10_category_rating.png も保存します。

使い方:
    docker compose exec lab python src/session10/effect_size.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # 画面を持たないコンテナ内で PNG として保存するための設定
import matplotlib.pyplot as plt

from common import OUT_DIR, format_p, load_reviews, mean_ci, print_result, ratings_by_category, welch_test


def overlaps(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """2 つの区間 (下限, 上限) が重なっているか。"""
    return a[0] <= b[1] and b[0] <= a[1]


def main() -> None:
    groups = ratings_by_category(load_reviews())

    small = welch_test(groups["小説"], groups["児童書"])
    print_result("小説 vs 児童書（有意だが小さい差）", small)
    print()
    none = welch_test(groups["技術書"], groups["ビジネス"])
    print_result("技術書 vs ビジネス（有意ではない）", none)

    # 1 群ごとの平均と 95% 信頼区間（図のエラーバーにも使う）
    order = sorted(groups, key=lambda c: -groups[c].mean())
    ci = {name: mean_ci(groups[name]) for name in order}

    print()
    print("■ 平均の 95% 信頼区間の重なり")
    for left, right in [("技術書", "ビジネス"), ("小説", "児童書")]:
        verdict = "重なる" if overlaps(ci[left][1:], ci[right][1:]) else "重ならない"
        print(f"  {left} と {right}: {verdict}")
    print(f"  技術書 vs ビジネス の p 値: {format_p(none['p'])}")
    print(f"  小説 vs 児童書 の p 値    : {format_p(small['p'])}")

    OUT_DIR.mkdir(exist_ok=True)
    means = [ci[name][0] for name in order]
    lower = [ci[name][0] - ci[name][1] for name in order]
    upper = [ci[name][2] - ci[name][0] for name in order]
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.errorbar(means, range(len(order)), xerr=[lower, upper], fmt="o", color="#4c78a8", capsize=4)
    ax.set_yticks(range(len(order)), order)
    ax.invert_yaxis()
    ax.set_xlabel("rating の平均（横棒は 95% 信頼区間）")
    ax.set_title("カテゴリ別の平均評価と 95% 信頼区間")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "s10_category_rating.png", dpi=120)
    plt.close(fig)
    print("\n図を保存しました: outputs/s10_category_rating.png")


if __name__ == "__main__":
    main()
