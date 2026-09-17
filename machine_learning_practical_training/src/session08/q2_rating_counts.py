"""問題2: 1 件しかない星 1 を「見える」図にする ― 数値ラベルと対数目盛。"""

from __future__ import annotations

import matplotlib.pyplot as plt

from common import load_reviews, save_fig


def main() -> None:
    reviews = load_reviews()
    counts = reviews["rating"].value_counts().sort_index()  # 星の昇順に並べる

    print("■ 星ごとの件数")
    for star, number in counts.items():
        print(f"星 {int(star)}: {int(number):,} 件")
    print(f"合計: {int(counts.sum()):,} 件")
    print(f"星が未入力のレビュー: {int(reviews['rating'].isna().sum())} 件")

    labels = [f"星 {int(star)}" for star in counts.index]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.2))

    bars = axes[0].barh(labels, counts.to_numpy(), color="#4c78a8")
    axes[0].bar_label(bars, fmt="%d 件", padding=3)  # 棒の右側に件数を書き込む
    axes[0].set_xlim(0, 11000)  # ラベルが枠外に出ないよう余白を作る
    axes[0].set_title("件数を数値で添える")
    axes[0].set_xlabel("件数")

    axes[1].barh(labels, counts.to_numpy(), color="#4c78a8")
    axes[1].set_xscale("log")  # 1 件と 9,325 件を同じ図に収める
    axes[1].set_title("横軸を対数目盛にする")
    axes[1].set_xlabel("件数（対数目盛）")

    save_fig(fig, "s08_q2_rating_counts.png")
    print("\n読み取り: 星 1 の 1 件は棒では見えないため、数値ラベルか対数目盛で補う必要がある")


if __name__ == "__main__":
    main()
