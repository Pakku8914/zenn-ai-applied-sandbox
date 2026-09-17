"""直線では確率にならない ―― シグモイド関数が何をしているかを数値と図で確かめる。

使い方:
    docker compose exec lab python src/session17/sigmoid_curve.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # 画面のない環境なのでファイルに保存する
import matplotlib.pyplot as plt
import numpy as np

from common import OUT_DIR, sigmoid

# 表示する対数オッズ（ロジット）の代表値
SAMPLE_LOGITS = [-3, -2, -1, 0, 1, 2, 3]
# 表示する確率の代表値
SAMPLE_PROBABILITIES = [0.2, 0.5, 0.8, 0.9]
# 右の図に引く「もし直線で確率を出そうとしたら」の線（説明のための補助線）
LINE_INTERCEPT = 0.5
LINE_SLOPE = 0.12


def odds(p: float) -> float:
    """確率をオッズ（起こる回数 : 起こらない回数）に変える。"""
    return p / (1 - p)


def logit(p: float) -> float:
    """確率を対数オッズに変える（シグモイドの逆向きの計算）。"""
    return float(np.log(odds(p)))


def draw(path) -> None:
    """左にシグモイド曲線、右に「直線で確率を出そうとすると破綻する」図を描く。"""
    z = np.linspace(-6, 6, 241)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))

    axes[0].plot(z, sigmoid(z), color="#4c78a8", linewidth=2)
    axes[0].axhline(0.5, color="#888888", linestyle="--", linewidth=1)
    axes[0].axvline(0, color="#888888", linestyle="--", linewidth=1)
    axes[0].set_title("シグモイド関数は必ず 0〜1 に収まる")
    axes[0].set_xlabel("対数オッズ z（= 係数と特徴量の足し算）")
    axes[0].set_ylabel("確率")
    axes[0].set_ylim(-0.35, 1.35)

    axes[1].plot(z, LINE_INTERCEPT + LINE_SLOPE * z, color="#e45756", linewidth=2, label="直線")
    axes[1].plot(z, sigmoid(z), color="#4c78a8", linewidth=2, label="シグモイド")
    axes[1].axhspan(1.0, 1.35, color="#cccccc", alpha=0.5)
    axes[1].axhspan(-0.35, 0.0, color="#cccccc", alpha=0.5)
    axes[1].set_title("直線は確率になれない（灰色は 0〜1 の外）")
    axes[1].set_xlabel("対数オッズ z")
    axes[1].set_ylabel("出力")
    axes[1].set_ylim(-0.35, 1.35)
    axes[1].legend(loc="upper left")

    fig.tight_layout()
    OUT_DIR.mkdir(exist_ok=True)
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main() -> None:
    print("■ 対数オッズ z を確率に変える（シグモイド関数）")
    for value in SAMPLE_LOGITS:
        print(f"z = {value:+d} → 確率 {sigmoid(value):.4f}")
    print()

    print("■ 確率 → オッズ → 対数オッズ → 確率（1 周して戻るか）")
    for p in SAMPLE_PROBABILITIES:
        z = logit(p)
        print(f"確率 {p:.2f} / オッズ {odds(p):.4f} / 対数オッズ {z:+.4f} / 戻した確率 {sigmoid(z):.4f}")
    print()

    print("■ 確率とオッズの違い（確率が 2 倍になってもオッズは 2 倍にならない）")
    for p in [0.4, 0.8]:
        print(f"確率 {p:.2f} → オッズ {odds(p):.4f}")
    print()

    path = OUT_DIR / "s17_sigmoid.png"
    draw(path)
    print(f"図を保存しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
