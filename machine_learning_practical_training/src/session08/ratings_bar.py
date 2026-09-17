"""数えられる値は棒グラフで ― 1 件しかない星 1 をどう見せるか。"""

from __future__ import annotations

import matplotlib.pyplot as plt

from common import load_reviews, save_fig


def main() -> None:
    reviews = load_reviews()
    counts = reviews["rating"].value_counts().sort_index()

    # 図の前に「件数表」を必ず出す。図では見えない 1 件も、表なら見える
    print("■ 星ごとの件数")
    for star, number in counts.items():
        print(f"星 {int(star)}: {int(number):,} 件")
    print(f"合計: {int(counts.sum()):,} 件")
    print(f"星が未入力のレビュー: {int(reviews['rating'].isna().sum())} 件")
    print(f"平均の星: {reviews['rating'].mean():.4f}")

    stars = [int(star) for star in counts.index]
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.2))
    axes[0].bar(stars, counts.to_numpy(), color="#4c78a8")
    axes[0].set_title("件数をそのまま（星 1 が見えない）")
    axes[1].bar(stars, counts.to_numpy(), color="#4c78a8")
    axes[1].set_yscale("log")  # 縦軸を対数にすると 1 件も 9,325 件も同じ図に収まる
    axes[1].set_title("縦軸を対数目盛にする（星 1 が見える）")
    for ax in axes:
        ax.set_xlabel("星の数")
        ax.set_ylabel("件数")
        ax.set_xticks(stars)
    fig.suptitle("件数の差が数千倍あるときは目盛りを変える")
    save_fig(fig, "s08_rating_bar.png")


if __name__ == "__main__":
    main()
