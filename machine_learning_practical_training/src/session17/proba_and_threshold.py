"""predict と predict_proba の違いと、閾値 0.5 が既定にすぎないことを確かめる。

使い方:
    docker compose exec lab python src/session17/proba_and_threshold.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from common import (
    DEFAULT_THRESHOLD,
    OUT_DIR,
    THRESHOLDS,
    fit_model,
    load_review_table,
    prepare,
    print_threshold_table,
    split_xy,
    threshold_table,
)

HEAD = 5  # 先頭何件を覗くか
# 図に描く閾値の刻み（0.05 から 0.95 まで）
CURVE_THRESHOLDS = np.round(np.arange(0.05, 1.00, 0.05), 2)


def draw(proba, table, path) -> None:
    """左に確率の分布、右に閾値ごとの指標の動きを描く。"""
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))

    axes[0].hist(proba, bins=40, color="#4c78a8")
    for t in THRESHOLDS:
        axes[0].axvline(t, color="#e45756", linestyle="--", linewidth=1)
    axes[0].set_title("予測確率の分布（赤い線が閾値）")
    axes[0].set_xlabel("高評価である予測確率")
    axes[0].set_ylabel("件数")

    for column, label in [("precision", "適合率"), ("recall", "再現率"), ("f1", "F1"), ("accuracy", "accuracy")]:
        axes[1].plot(table["threshold"], table[column], marker="o", markersize=3, label=label)
    axes[1].axvline(DEFAULT_THRESHOLD, color="#888888", linestyle="--", linewidth=1)
    axes[1].set_title("閾値を動かすと指標はこう動く")
    axes[1].set_xlabel("閾値")
    axes[1].set_ylabel("値")
    axes[1].set_ylim(0.0, 1.05)
    axes[1].legend(loc="lower left", fontsize=9)

    fig.tight_layout()
    OUT_DIR.mkdir(exist_ok=True)
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    model = fit_model(train, y_train)

    proba = model.predict_proba(test)[:, 1]  # 列 1 が「高評価である確率」
    predicted = model.predict(test)
    print(f"■ predict_proba と predict（評価データの先頭 {HEAD} 件）")
    for i in range(HEAD):
        print(f"{i + 1} 件目: 確率 {proba[i]:.4f} → predict {predicted[i]}")
    print(f"クラスの並び（model.classes_）: {model.classes_}")
    print()

    by_hand = (proba >= DEFAULT_THRESHOLD).astype("int64")
    print("■ predict は「確率を 0.5 で切っただけ」なのか")
    print(f"手で 0.5 で切った結果と predict が完全に一致するか: {bool((by_hand == predicted).all())}")
    print(f"評価データ {len(y_test):,} 件 / 正例率 {y_test.mean():.4f}")
    print()

    table = threshold_table(y_test, proba)
    print("■ 閾値を動かすと何が変わるか（陽性 = 高評価）")
    print_threshold_table(table)
    print()
    best = table.loc[table["accuracy"].idxmax()]
    print(f"accuracy が最大になる閾値: {best['threshold']:.1f}（accuracy {best['accuracy']:.4f}）")
    print("→ ただし「accuracy が最大の閾値を選ぶ」は業務上の正解ではありません（セッション20 で扱います）。")
    print()

    path = OUT_DIR / "s17_threshold_tradeoff.png"
    draw(proba, threshold_table(y_test, proba, CURVE_THRESHOLDS), path)
    print(f"図を保存しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
