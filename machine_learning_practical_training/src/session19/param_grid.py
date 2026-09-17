"""n_estimators と learning_rate を手で数段階だけ変えて、既定値が最良かどうかを確かめる。

使い方:
    docker compose exec lab python src/session19/param_grid.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # 画面のない環境なのでファイルに保存する
import matplotlib.pyplot as plt
import pandas as pd

from common import OUT_DIR, fit_and_score, load_review_table, make_lgbm, prepare, split_xy

# 手で試す組み合わせ（体系的な探索はセッション23 で扱います）
COMBINATIONS = [(50, 0.05), (50, 0.1), (200, 0.05), (200, 0.1)]
# 比べる相手として引く線（セッション17 で実測したロジスティック回帰の ROC AUC）
LINEAR_ROC_AUC = 0.8265


def build_table(train, y_train, test, y_test) -> pd.DataFrame:
    """組み合わせごとに学習して accuracy と ROC AUC を並べた表を作る。"""
    rows = []
    for n_estimators, learning_rate in COMBINATIONS:
        _, scores = fit_and_score(
            make_lgbm(n_estimators=n_estimators, learning_rate=learning_rate),
            train,
            y_train,
            test,
            y_test,
        )
        rows.append(
            {
                "n_estimators": n_estimators,
                "learning_rate": learning_rate,
                "accuracy": scores["accuracy"],
                "roc_auc": scores["roc_auc"],
            }
        )
    return pd.DataFrame(rows)


def draw(path, table: pd.DataFrame) -> None:
    """組み合わせごとの ROC AUC を棒で並べ、ロジスティック回帰の水準に線を引く。"""
    labels = [f"{row.n_estimators} 本\nlr {row.learning_rate}" for row in table.itertuples(index=False)]
    colors = ["#4c78a8"] * len(table)
    colors[int(table["roc_auc"].idxmin())] = "#e45756"  # いちばん悪い組み合わせを赤で示す
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.bar(labels, table["roc_auc"], color=colors)
    ax.axhline(LINEAR_ROC_AUC, color="#54a24b", linestyle="--", linewidth=1.5)
    ax.text(len(table) - 0.4, LINEAR_ROC_AUC + 0.001, f"ロジスティック回帰 {LINEAR_ROC_AUC:.4f}", ha="right", color="#54a24b")
    ax.set_ylim(0.78, 0.84)
    ax.set_ylabel("評価データの ROC AUC")
    ax.set_title("既定値（200 本・lr 0.1）がいちばん悪い")
    for index, value in enumerate(table["roc_auc"]):
        ax.text(index, value + 0.0012, f"{value:.4f}", ha="center")
    fig.tight_layout()
    OUT_DIR.mkdir(exist_ok=True)
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    table = build_table(train, y_train, test, y_test)

    print("■ 手で 4 通りだけ試す")
    print("n_estimators | learning_rate | accuracy | ROC AUC")
    for row in table.itertuples(index=False):
        print(f"{row.n_estimators:>12} | {row.learning_rate:>13} |  {row.accuracy:.4f}  | {row.roc_auc:.4f}")
    print()

    best_rows = table.loc[table["roc_auc"] >= table["roc_auc"].max() - 0.0001]
    worst = table.loc[table["roc_auc"].idxmin()]
    best_counts = sorted({int(value) for value in best_rows["n_estimators"]})
    print(f"ROC AUC が最大の行の木の本数: {best_counts} 本（{table['roc_auc'].max():.4f}）")
    print(f"ROC AUC が最小: {int(worst.n_estimators)} 本・lr {worst.learning_rate}（{worst.roc_auc:.4f}）")
    print(f"既定値（200 本・lr 0.1）は 4 通りの中で最下位か: {bool(worst.n_estimators == 200 and worst.learning_rate == 0.1)}")
    print()
    print("判断: 木を増やすと良くなるとは限りません。このデータでは 200 本は多すぎて過学習側に振れています。")

    path = OUT_DIR / "s19_param_grid.png"
    draw(path, table)
    print(f"図を保存しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
