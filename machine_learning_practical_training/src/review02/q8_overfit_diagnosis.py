"""実装問題 8：過学習の診断（深さの表 → 学習曲線 → 2 パターンの判定）。

使い方:
    docker compose exec lab python src/review02/q8_overfit_diagnosis.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # pyplot より前に書く（画面のないコンテナで図を保存するため）
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier

from common import (
    CLF_FEATURES,
    CLF_TARGET,
    GAP_LIMIT,
    LOW_AUC,
    MAX_ITER,
    RANDOM_STATE,
    depth_table,
    learning_curve_of,
    load_review_table,
    save_fig,
    split_classification,
)


def step1_depth(X_train, X_test, y_train, y_test) -> list[dict]:
    """深さを変えて、訓練と評価の AUC を必ず 2 本並べる（セッション15・18）。"""
    rows = depth_table(X_train, y_train, X_test, y_test)
    print("■ 1. 決定木の深さを変える（訓練と評価を必ず並べる）")
    for row in rows:
        print(
            f"  深さ {row['label']}: 葉 {row['leaves']:,} 枚 / 訓練 AUC {row['train_auc']:.4f}"
            f" / 評価 AUC {row['test_auc']:.4f} / {row['diagnosis']}"
        )
    best = max(rows, key=lambda r: r["test_auc"])
    deepest = max(rows, key=lambda r: r["train_auc"])
    print(f"  評価 AUC が最も高い深さ: {best['label']}（{best['test_auc']:.4f}）")
    print(f"  訓練 AUC が最も高い深さ: {deepest['label']}（{deepest['train_auc']:.4f}）")
    print(f"  診断の線引き: 訓練 AUC < {LOW_AUC:.2f} なら未学習 / 差 > {GAP_LIMIT:.2f} なら過学習")
    print(f"  検算 訓練 AUC が最も高い深さは評価 AUC の最良ではない: {best['label'] != deepest['label']}")
    print(f"  検算 葉の数が深さ 1 の 1,000 倍以上に増える: {rows[-1]['leaves'] >= rows[0]['leaves'] * 1000}")
    return rows


def step2_curves(df) -> tuple[dict, dict]:
    """学習曲線を 2 つ描いて、形の違いを数値で言い切る（セッション15）。"""
    X, y = df[CLF_FEATURES], df[CLF_TARGET]
    linear = learning_curve_of(LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE), X, y)
    tree = learning_curve_of(DecisionTreeClassifier(random_state=RANDOM_STATE), X, y)

    print("■ 2. 学習曲線（5 分割の交差検証・指標は ROC AUC）")
    print("  試した件数: " + " / ".join(f"{n:,}" for n in linear["sizes"]))
    print(
        f"  ロジスティック回帰: 訓練 {linear['train'][0]:.4f} → {linear['train'][-1]:.4f}"
        f" / 検証 {linear['valid'][0]:.4f} → {linear['valid'][-1]:.4f}"
    )
    print(
        f"  深さ無制限の決定木: 訓練 {tree['train'][0]:.4f} → {tree['train'][-1]:.4f}"
        f" / 検証 {tree['valid'][0]:.4f} → {tree['valid'][-1]:.4f}"
    )
    print(f"  ロジスティック回帰は最大件数で 2 本が接近（差 < 0.01）: {linear['train'][-1] - linear['valid'][-1] < 0.01}")
    print(f"  決定木は最大件数でも 2 本が開いたまま（差 > 0.30）: {tree['train'][-1] - tree['valid'][-1] > 0.30}")
    print(f"  件数を 20 倍にしたロジスティック回帰の検証 AUC の伸びが 0.01 未満: {linear['valid'][-1] - linear['valid'][0] < 0.01}")
    print(f"  決定木の検証 AUC が一度もロジスティック回帰を上回らない: {max(tree['valid']) < min(linear['valid'])}")
    print("  判定: ロジスティック回帰は「2 本が接近して伸びが止まった」= 件数を増やしても効かない")
    print("  判定: 決定木は「2 本が開いたまま」= 過学習。深さを抑えるか件数を増やす")
    return linear, tree


def step3_figure(rows: list[dict], linear: dict, tree: dict) -> None:
    """診断に使った 2 枚を 1 枚の図にまとめて保存する（セッション8 の作法）。"""
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))

    positions = list(range(len(rows)))
    axes[0].plot(positions, [r["train_auc"] for r in rows], marker="o", label="訓練データ")
    axes[0].plot(positions, [r["test_auc"] for r in rows], marker="s", linestyle="--", label="評価データ")
    axes[0].set_xticks(positions)
    axes[0].set_xticklabels([r["label"] for r in rows])
    axes[0].set_xlabel("決定木の深さ")
    axes[0].set_ylabel("ROC AUC")
    axes[0].set_ylim(0.55, 1.02)
    axes[0].set_title("深さを上げると訓練だけが伸びる")
    axes[0].legend()
    axes[0].grid(alpha=0.3)

    axes[1].plot(linear["sizes"], linear["train"], marker="o", color="#4c78a8", label="ロジスティック回帰・訓練")
    axes[1].plot(linear["sizes"], linear["valid"], marker="o", linestyle="--", color="#4c78a8", label="ロジスティック回帰・検証")
    axes[1].plot(tree["sizes"], tree["train"], marker="s", color="#e45756", label="決定木（無制限）・訓練")
    axes[1].plot(tree["sizes"], tree["valid"], marker="s", linestyle="--", color="#e45756", label="決定木（無制限）・検証")
    axes[1].set_xlabel("訓練に使った件数")
    axes[1].set_ylabel("ROC AUC")
    axes[1].set_ylim(0.55, 1.02)
    axes[1].set_title("学習曲線（接近するか、開いたままか）")
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.3)

    fig.tight_layout()
    save_fig(fig, "review02_overfit_diagnosis.png")


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_classification(df)
    rows = step1_depth(X_train, X_test, y_train, y_test)
    linear, tree = step2_curves(df)
    step3_figure(rows, linear, tree)


if __name__ == "__main__":
    main()
