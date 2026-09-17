"""多クラス分類（星 1〜5）で平均の取り方を選ぶ。層化分割ができない場面も実演する。

使い方:
    docker compose exec lab python src/session20/multiclass_average.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from common import (
    average_scores,
    fit_star_model,
    load_review_table,
    multiclass_confusion,
    print_multiclass_confusion,
    save_figure,
    split_star,
    star_counts,
    stratify_error_message,
)

FIGURE_NAME = "s20_multiclass_confusion.png"


def draw(labels, matrix, path_name: str):
    """混同行列を「行ごとの割合」で塗り、件数を書き込む。"""
    counts = matrix.astype("float64")
    ratios = counts / counts.sum(axis=1, keepdims=True)

    fig, ax = plt.subplots(figsize=(6.2, 5.2))
    ax.imshow(ratios, cmap="Blues", vmin=0.0, vmax=1.0)
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(
                j,
                i,
                f"{int(counts[i, j]):,}",
                ha="center",
                va="center",
                fontsize=11,
                color="#222222" if ratios[i, j] < 0.6 else "#ffffff",
            )
    ax.set_xticks(range(len(labels)), [f"予測 星{label}" for label in labels])
    ax.set_yticks(range(len(labels)), [f"実測 星{label}" for label in labels])
    ax.set_title("星 1〜5 の混同行列（数字は件数、色は行ごとの割合）")
    fig.tight_layout()
    path = save_figure(fig, path_name)
    plt.close(fig)
    return path


def main() -> None:
    df = load_review_table()

    counts = star_counts(df)
    print(f"■ 星の件数（{len(df):,} 件）")
    for star, count in counts.items():
        print(f"星{star}: {count:>6,} 件")
    print()

    print("■ stratify=y で分けようとすると（星1 が 1 件しかないため）")
    print(f"ValueError: {stratify_error_message(df)}")
    print()

    X_train, X_test, _, _ = split_star(df)
    print(f"■ stratify なしで 5 クラス分類（訓練 {len(X_train):,} 件 / 評価 {len(X_test):,} 件）")
    y_test, y_pred, model = fit_star_model(df)
    scores = average_scores(y_test, y_pred)
    print(f"accuracy    : {scores['accuracy']:.4f}")
    print(f"macro F1    : {scores['macro_f1']:.4f}")
    print(f"micro F1    : {scores['micro_f1']:.4f}")
    print(f"weighted F1 : {scores['weighted_f1']:.4f}")
    print()

    print(f"モデルが知っているクラス: {[int(v) for v in model.classes_]}")
    print(f"評価データに実際にあったクラス: {[int(v) for v in np.unique(y_test)]}")
    print(f"予測に現れたクラス: {[int(v) for v in np.unique(y_pred)]}")
    print()

    labels, matrix = multiclass_confusion(y_test, y_pred)
    print("■ 混同行列")
    print_multiclass_confusion(labels, matrix)
    print()

    path = draw(labels, matrix, FIGURE_NAME)
    print(f"図を保存しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
