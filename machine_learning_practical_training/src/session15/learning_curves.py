"""学習曲線を 2 パターン描いて、読み方を覚える。

使い方:
    docker compose exec lab python src/session15/learning_curves.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier

from common import (
    CV_FOLDS,
    FEATURES,
    MAX_ITER,
    OUT_DIR,
    RANDOM_STATE,
    TARGET,
    TRAIN_SIZES,
    learning_curve_of,
    load_review_features,
    pad,
)

# 2 本の線の開き方をどこで判定するか
CLOSE_GAP = 0.01  # これ未満なら「接近している」＝データを増やしても伸びない
WIDE_GAP = 0.30  # これより大きければ「開いたまま」＝過学習
PLATEAU_LIMIT = 0.65  # 件数を増やしても検証スコアがこの線を越えないことの確認に使う


def plot_curves(sizes: list[int], curves: list[tuple[str, list[float], list[float]]], path) -> None:
    """左右に並べて、2 本の線の開き方の違いを見せる。"""
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.0), sharey=True)
    for ax, (title, train, valid) in zip(axes, curves):
        ax.plot(sizes, train, marker="o", color="#e45756", label="訓練データ")
        ax.plot(sizes, valid, marker="o", color="#4c78a8", label="検証データ")
        ax.set_title(title)
        ax.set_xlabel("学習に使った件数")
        ax.set_ylim(0.55, 1.03)
        ax.legend(loc="center right")
    axes[0].set_ylabel("ROC AUC（5 分割の平均）")
    fig.suptitle("2 本が接近＝データを増やしても伸びない / 開いたまま＝過学習")
    fig.tight_layout()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main() -> None:
    df = load_review_features()
    # 学習曲線は交差検証で分割するので、分割前の全データ（14,169 件）を渡す
    X, y = df[FEATURES], df[TARGET]

    models = [
        ("ロジスティック回帰", LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)),
        ("決定木（深さの制限なし）", DecisionTreeClassifier(random_state=RANDOM_STATE)),
    ]

    print(f"■ 学習曲線（train_sizes={TRAIN_SIZES} / cv={CV_FOLDS} / scoring=roc_auc）")
    results = []
    for label, model in models:
        sizes, train, valid = learning_curve_of(model, X, y)
        results.append((label, sizes, train, valid))
    print(f"学習に使った件数 : {' / '.join(f'{n:,}' for n in results[0][1])}")
    print()

    for label, sizes, train, valid in results:
        print(f"▼ {label}")
        print("件数    | 訓練 AUC | 検証 AUC")
        for n, t, v in zip(sizes, train, valid):
            print(f"{n:<7,} | {t:>8.4f} | {v:>8.4f}")
        print()

    print(f"■ いちばん右（{results[0][1][-1]:,} 件）での読み取り")
    gaps = {}
    for label, _, train, valid in results:
        gaps[label] = train[-1] - valid[-1]
    lr_label, tree_label = results[0][0], results[1][0]
    print(f"{pad(lr_label)} : 2 本の差が {CLOSE_GAP} 未満か : {gaps[lr_label] < CLOSE_GAP}")
    print(f"{pad(tree_label)} : 2 本の差が {WIDE_GAP} より大きいか : {gaps[tree_label] > WIDE_GAP}")
    better = max(results, key=lambda r: r[3][-1])[0]
    print(f"検証 AUC が高いのはどちらか : {better}")
    # 件数を 20 倍にしても検証スコアがほとんど動かない＝データ不足ではない
    tree_valid = results[1][3]
    print(f"決定木の検証 AUC が件数 20 倍でも {PLATEAU_LIMIT} に届かないか : "
          f"{max(tree_valid) < PLATEAU_LIMIT}")
    print()

    plot_curves(
        results[0][1],
        [(label, train, valid) for label, _, train, valid in results],
        OUT_DIR / "s15_learning_curve.png",
    )
    print("図を保存しました: outputs/s15_learning_curve.png")


if __name__ == "__main__":
    main()
