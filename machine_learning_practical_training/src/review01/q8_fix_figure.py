"""実装問題 8：誤解を招く図を直す ― 同じデータで「悪い例」と「良い例」を並べる。

使い方:
    docker compose exec lab python src/review01/q8_fix_figure.py
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import CATEGORY_ORDER, load_rated_reviews, load_reviews, mean_ci, save_fig

PROBLEMS = [
    "① 縦軸が 3.6 から始まっている → 星は 1 〜 5 の値なので 0 から描く（軸を切ると差が誇張される）",
    "② 件数が図に無い → 児童書と技術書では件数が 3 倍違う。件数と 95% 信頼区間を添える",
    "③ 5 段階を bins=10 で描いている → 棒の幅が意味を持たない。星ごとの件数を数えて棒にする",
    "④ 星 1（1 件）と星 2（38 件）が見えない → 対数目盛にし、件数の数値ラベルを添える",
    "⑤ 星が未入力の 298 件が図から消えている → 母集団（14,169 件）を図の中に明記する",
]


def category_table(reviews: pd.DataFrame) -> pd.DataFrame:
    """カテゴリ別の件数・平均の星・95% 信頼区間。並びは平均価格の安い順に固定する。"""
    rows = []
    for name in CATEGORY_ORDER:
        values = reviews.loc[reviews["category"] == name, "rating"]
        mean, low, high = mean_ci(values)
        rows.append({"category": name, "n": len(values), "mean": mean, "low": low, "high": high})
    return pd.DataFrame(rows)


def main() -> None:
    reviews = load_rated_reviews()
    missing = int(load_reviews()["rating"].isna().sum())
    table = category_table(reviews)
    counts = reviews["rating"].value_counts().sort_index()

    print("■ 図の元にした数値")
    print(f"  星が入っているレビュー: {len(reviews):,} 件（未入力 {missing} 件を除外）")
    print("  星ごとの件数: " + " / ".join(f"星{int(s)} {int(n):,} 件" for s, n in counts.items()))
    for row in table.itertuples():
        print(f"  {row.category}: {row.n:,} 件 / 平均の星 {row.mean:.4f}")

    print("■ 悪い図の問題点と直し方")
    for line in PROBLEMS:
        print(f"  {line}")

    fig, axes = plt.subplots(2, 2, figsize=(11, 7.4))
    bad_bar, bad_hist = axes[0]
    good_bar, good_count = axes[1]

    # 悪い例 1：縦軸を切った棒グラフ（わずかな差が「大差」に見える）
    bad_bar.bar(table["category"].tolist(), table["mean"].to_numpy(), color="#e45756")
    bad_bar.set_ylim(3.6, 4.5)
    bad_bar.set_title("悪い例：縦軸を 3.6 から始めた平均の星")
    bad_bar.set_ylabel("平均の星")

    # 悪い例 2：5 段階の値を bins=10 のヒストグラムで描く
    bad_hist.hist(reviews["rating"].to_numpy(), bins=10, color="#e45756")
    bad_hist.set_title("悪い例：5 段階を bins=10 で描いた分布")
    bad_hist.set_xlabel("星")
    bad_hist.set_ylabel("件数")

    # 良い例 1：0 から描き、件数と 95% 信頼区間を添える
    err = np.vstack(
        [
            table["mean"].to_numpy() - table["low"].to_numpy(),
            table["high"].to_numpy() - table["mean"].to_numpy(),
        ]
    )
    good_bar.bar(
        [f"{row.category}\n{row.n:,} 件" for row in table.itertuples()],
        table["mean"].to_numpy(),
        yerr=err,
        capsize=4,
        color="#4c78a8",
    )
    good_bar.set_ylim(0, 5)
    good_bar.set_yticks([0, 1, 2, 3, 4, 5])
    good_bar.set_title("良い例：0 から描き、件数と 95% 信頼区間を添える")
    good_bar.set_ylabel("平均の星")

    # 良い例 2：星ごとの件数を数え、対数目盛と数値ラベルで少数の星も見えるようにする
    bars = good_count.bar(
        [str(int(star)) for star in counts.index], counts.to_numpy(), color="#4c78a8"
    )
    good_count.bar_label(bars, labels=[f"{int(n):,}" for n in counts], padding=2)
    good_count.set_yscale("log")
    good_count.set_ylim(0.5, 40000)
    good_count.set_title(f"良い例：星ごとの件数（未入力 {missing} 件は図の外に明記）")
    good_count.set_xlabel("星")
    good_count.set_ylabel("件数（対数目盛）")

    fig.suptitle(f"同じ {len(reviews):,} 件のレビュー。上が誤解を招く図、下が直した図")
    save_fig(fig, "review01_bad_vs_good.png")


if __name__ == "__main__":
    main()
