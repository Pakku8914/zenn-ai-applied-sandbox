"""問題4: 同じ数値から「誠実な図」と「誇張した図」を作る。"""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from common import load_rated_reviews, save_fig

BAND_LABELS = ["Q1（安）", "Q2", "Q3", "Q4（高）"]


def main() -> None:
    reviews = load_rated_reviews()  # 星が未入力の 298 件は落としてある
    reviews["価格帯"] = pd.qcut(reviews["price"], 4, labels=BAND_LABELS)
    band_mean = reviews.groupby("価格帯", observed=True)["rating"].mean()

    print("■ 価格帯ごとの平均の星")
    for band, value in band_mean.items():
        print(f"{band}: {value:.4f}")
    print(f"Q3 と Q4 の差: {abs(band_mean['Q4（高）'] - band_mean['Q3']):.3f}")

    settings = [((1, 5), "尺度いっぱい（1〜5）：誠実な図"), ((3.7, 4.4), "軸を切った図（3.7〜4.4）：誇張した図")]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    for ax, (ylim, title) in zip(axes, settings):
        ax.bar(BAND_LABELS, band_mean.to_numpy(), color="#f58518")  # 同じ数値を渡す
        ax.set_ylim(*ylim)
        ax.set_title(title)
        ax.set_xlabel("価格帯（4 分位）")
        ax.set_ylabel("平均の星")
    save_fig(fig, "s08_q4_band_axis.png")

    print("\n判断1: 報告には左（1〜5）を使う。星は 1〜5 の尺度なので、尺度の全体を見せるのが誠実である")
    print("判断2: 右では Q1 の棒が Q3 の数倍の高さに見えるが、実際の差は 0.6 ポイントほどしかない")
    print("判断3: Q3 と Q4 の差は 0.01 未満なので、「高いほど低評価」ではなく「Q3 で下げ止まる」と報告する")


if __name__ == "__main__":
    main()
