"""決定木の深さを変えて、訓練と評価のスコアが分かれていく様子を見る。

使い方:
    docker compose exec lab python src/session15/tree_depth.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.dummy import DummyClassifier

from common import (
    OUT_DIR,
    RANDOM_STATE,
    depth_table,
    fit_and_score,
    load_review_features,
    pad,
    split_features,
)

# 診断の境目。数字を式の中に直接書かず、名前を付けて 1 か所に集める
LOW_TRAIN_AUC = 0.70  # 訓練データでこれに届かないなら、そもそも学習しきれていない
GAP_LIMIT = 0.05  # 訓練と評価の差がこれを超えたら過学習を疑う


def diagnose(train_auc: float, eval_auc: float) -> str:
    """訓練と評価のスコアの組から、未学習・過学習・釣り合いを判定する。"""
    if train_auc < LOW_TRAIN_AUC:
        return "未学習（バイアスが大きい）"
    if train_auc - eval_auc > GAP_LIMIT:
        return "過学習（バリアンスが大きい）"
    return "釣り合っている"


def plot_depth_curve(table: list[dict], path) -> None:
    """深さを横軸にして、訓練と評価の ROC AUC を重ねて描く。"""
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    positions = list(range(len(table)))
    ax.plot(positions, [r["train_auc"] for r in table], marker="o", color="#e45756", label="訓練データ")
    ax.plot(positions, [r["test_auc"] for r in table], marker="o", color="#4c78a8", label="評価データ")
    ax.axhline(0.5, linestyle="--", color="gray", label="当て推量（0.5000）")
    ax.set_xticks(positions)
    ax.set_xticklabels([r["label"] for r in table])
    ax.set_xlabel("決定木の深さ（右へ行くほど複雑）")
    ax.set_ylabel("ROC AUC")
    ax.set_ylim(0.45, 1.02)
    ax.set_title("深くするほど訓練は上がり、評価は途中から下がる")
    ax.legend(loc="lower left")
    fig.tight_layout()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main() -> None:
    X_train, X_test, y_train, y_test = split_features(load_review_features())
    base = fit_and_score(
        DummyClassifier(strategy="most_frequent", random_state=RANDOM_STATE),
        X_train,
        y_train,
        X_test,
        y_test,
    )
    table = depth_table(X_train, y_train, X_test, y_test)

    print(f"■ 決定木の深さを変えて過学習を見る（訓練 {len(X_train):,} 件 / 評価 {len(X_test):,} 件）")
    print(f"{pad('深さ', 8)} | 葉の数 | 訓練 AUC | 評価 AUC | 評価 accuracy")
    for row in table:
        print(
            f"{pad(row['label'], 8)} | {row['leaves']:>6,} | {row['train_auc']:>8.4f} | "
            f"{row['test_auc']:>8.4f} | {row['test_accuracy']:>13.4f}"
        )
    print()

    best_eval = max(table, key=lambda r: r["test_auc"])
    best_train = max(table, key=lambda r: r["train_auc"])
    over = [r for r in table if r["train_auc"] > r["test_auc"]]
    below_base = [r for r in table if r["test_accuracy"] < base["accuracy"]]
    print("■ 読み取り")
    print(f"評価 AUC がいちばん高い深さ : {best_eval['label']}")
    print(f"訓練 AUC がいちばん高い深さ : {best_train['label']}")
    print(f"訓練 AUC が評価 AUC を上回りはじめる深さ : {over[0]['label']}")
    shallow = table[0]
    print(f"深さ 1 の評価 accuracy がベースラインと一致するか : "
          f"{round(shallow['test_accuracy'], 4) == round(base['accuracy'], 4)}")
    print(f"評価 accuracy がベースラインを下回る深さ : {' / '.join(r['label'] for r in below_base)}")
    leaves = [r["leaves"] for r in table]
    print(f"葉の数 : {leaves[0]:,} 枚 → {leaves[-1]:,} 枚（1,000 倍以上に増えたか : "
          f"{leaves[-1] >= leaves[0] * 1000}）")
    print()

    print(f"■ 深さごとの診断（訓練 AUC が {LOW_TRAIN_AUC} 未満なら未学習、"
          f"訓練 - 評価 が {GAP_LIMIT} を超えたら過学習）")
    for row in table:
        print(f"{pad(row['label'], 8)} : {diagnose(row['train_auc'], row['test_auc'])}")
    print()

    plot_depth_curve(table, OUT_DIR / "s15_tree_depth.png")
    print("図を保存しました: outputs/s15_tree_depth.png")


if __name__ == "__main__":
    main()
