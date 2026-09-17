"""決定木の深さを変えて、葉がどこまで細かくなるか・過学習がどこから始まるかを見る。

使い方:
    docker compose exec lab python src/session18/tree_depth_again.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import OUT_DIR, baseline_scores, depth_table, load_review_table, pad, split_xy


def plot_depth(table: list[dict], path) -> None:
    """左の軸に訓練・評価の ROC AUC、右の軸に葉の数（対数目盛）を重ねる。"""
    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    positions = list(range(len(table)))
    ax.plot(positions, [r["train_auc"] for r in table], marker="o", color="#e45756", label="訓練データの AUC")
    ax.plot(positions, [r["test_auc"] for r in table], marker="o", color="#4c78a8", label="評価データの AUC")
    ax.axhline(0.5, linestyle="--", color="gray", label="当て推量（0.5000）")
    ax.set_xticks(positions)
    ax.set_xticklabels([r["label"] for r in table])
    ax.set_xlabel("決定木の深さ（右へ行くほど複雑）")
    ax.set_ylabel("ROC AUC")
    ax.set_ylim(0.45, 1.02)
    ax.set_title("葉が増えるほど訓練は上がり、評価は途中から下がる")

    right = ax.twinx()
    right.plot(positions, [r["leaves"] for r in table], marker="s", color="#54a24b", label="葉の数（右軸）")
    right.set_yscale("log")
    right.set_ylabel("葉の数（対数目盛）")

    handles, labels = ax.get_legend_handles_labels()
    extra_handles, extra_labels = right.get_legend_handles_labels()
    ax.legend(handles + extra_handles, labels + extra_labels, loc="center left", fontsize=9)
    fig.tight_layout()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main() -> None:
    X_train, X_test, y_train, y_test = split_xy(load_review_table())
    base = baseline_scores(y_test)
    table = depth_table(X_train, y_train, X_test, y_test)

    print(f"■ 決定木の深さを変えて過学習を見る（訓練 {len(X_train):,} 件 / 評価 {len(X_test):,} 件）")
    print(f"{pad('深さ', 9)}| 葉の数 | 訓練 AUC | 評価 AUC | 評価 accuracy")
    for row in table:
        print(
            f"{pad(row['label'], 9)}| {row['leaves']:>6,} | {row['train_auc']:>8.4f} | "
            f"{row['test_auc']:>8.4f} | {row['test_accuracy']:>13.4f}"
        )
    print()

    print(f"■ 葉 1 枚が見ている訓練データの件数（{len(X_train):,} 件 ÷ 葉の数）")
    for row in table:
        print(
            f"深さ {pad(row['label'], 9)}: 葉 {row['leaves']:>5,} 枚 / ノード {row['nodes']:>5,} 個 / "
            f"葉 1 枚あたり {len(X_train) / row['leaves']:>9,.1f} 件"
        )
    print()

    best = max(table, key=lambda row: row["test_auc"])
    worst = min(table, key=lambda row: row["test_auc"])
    print("■ 読み取り")
    print(f"評価 AUC がいちばん高い深さ : {best['label']}（{best['test_auc']:.4f}）")
    print(f"評価 AUC がいちばん低い深さ : {worst['label']}（{worst['test_auc']:.4f}）")
    print(f"ベースラインの accuracy : {base['accuracy']:.4f}")
    below = [row["label"] for row in table if row["test_accuracy"] < base["accuracy"]]
    print(f"評価 accuracy がベースラインを下回る深さ : {' / '.join(below)}")
    print()

    plot_depth(table, OUT_DIR / "s18_depth_overfit.png")
    print("図を保存しました: outputs/s18_depth_overfit.png")


if __name__ == "__main__":
    main()
