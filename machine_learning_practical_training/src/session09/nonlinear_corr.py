"""相関係数が「直線的な関係の強さ」しか測らないことを、3 つの関係で確かめる。

使い方:
    docker compose exec lab python src/session09/nonlinear_corr.py
"""

from __future__ import annotations

from common import make_toy_curves, pad_ja

CURVES = [
    ("line", "直線 y = 2x + 1"),
    ("parabola", "放物線 y = x^2"),
    ("cubic", "単調な曲線 y = x^3"),
]


def main() -> None:
    toy = make_toy_curves()

    print("■ 3 通りの関係（x が -3 〜 3 の 7 点）")
    for column, label in CURVES:
        pearson = toy["x"].corr(toy[column])
        spearman = toy["x"].corr(toy[column], method="spearman")
        print(f"{pad_ja(label, 20)}: ピアソン {pearson:+.4f} / スピアマン {spearman:+.4f}")


if __name__ == "__main__":
    main()
