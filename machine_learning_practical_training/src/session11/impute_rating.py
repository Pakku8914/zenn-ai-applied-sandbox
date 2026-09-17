"""rating の欠損を平均で埋めると何が起きるか（ばらつきが縮む）を数値と図で確かめる。

使い方:
    docker compose exec lab python src/session11/impute_rating.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from common import OUT_DIR, load_reviews

STARS = (1.0, 2.0, 3.0, 4.0, 5.0)  # もともと存在する値（これ以外の棒は代入で作られた棒）


def save_figure(observed: pd.Series, filled: pd.Series, mean_value: float) -> None:
    """星の分布を「欠損を落とした場合」と「平均で埋めた場合」で並べて保存する。"""
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.8), sharey=True)
    panels = [
        (axes[0], observed, f"欠損を落とす（{len(observed):,} 件）"),
        (axes[1], filled.round(4), f"平均 {mean_value:.4f} で埋める（{len(filled):,} 件）"),
    ]
    for ax, series, title in panels:
        counts = series.value_counts().sort_index()
        colors = ["#e45756" if value not in STARS else "#4c78a8" for value in counts.index]
        ax.bar(range(len(counts)), counts.to_numpy(), color=colors)
        ax.set_xticks(range(len(counts)), [f"{value:g}" for value in counts.index], rotation=45)
        ax.set_title(title)
        ax.set_xlabel("星の数")
    axes[0].set_ylabel("件数")
    fig.suptitle("平均で埋めると、元のデータに存在しない値の棒（赤）が立つ")
    fig.tight_layout()
    OUT_DIR.mkdir(exist_ok=True)
    fig.savefig(OUT_DIR / "s11_rating_impute.png", dpi=120)
    plt.close(fig)


def main() -> None:
    reviews = load_reviews()
    observed = reviews["rating"].dropna()

    print("■ 方針 A: 欠損を落とす")
    print(
        f"  件数 {len(observed):,} / 平均 {observed.mean():.4f}"
        f" / 標準偏差 {observed.std(ddof=1):.4f}"
    )

    mean_value = float(observed.mean())
    filled = reviews["rating"].fillna(mean_value)
    print("■ 方針 B: 平均で埋める")
    print(f"  件数 {len(filled):,} / 平均 {filled.mean():.4f} / 標準偏差 {filled.std(ddof=1):.4f}")
    print(
        f"  平均は動かないのに、標準偏差は {observed.std(ddof=1):.4f}"
        f" → {filled.std(ddof=1):.4f} に縮んだ"
    )
    print(f"  縮んだ理由: 298 件を平均そのものにしたので、平均からのずれが 0 の行が {298 / len(filled):.2%} 増えた")

    save_figure(observed, filled, mean_value)
    print("■ 図を保存しました: outputs/s11_rating_impute.png")


if __name__ == "__main__":
    main()
