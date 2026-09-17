"""ブースティングとバギングの違いを、木を増やしたときの ROC AUC の動きで確かめる。

使い方:
    docker compose exec lab python src/session19/boosting_vs_bagging.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # 画面のない環境なのでファイルに保存する
import matplotlib.pyplot as plt
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

from common import (
    N_ESTIMATORS,
    OUT_DIR,
    RANDOM_STATE,
    load_review_table,
    make_lgbm,
    prepare,
    proba_at,
    split_xy,
)

# 何本目までを使った時点で測るか
TREE_COUNTS = [1, 5, 20, 50, 100, 200]


def forest_probas(forest: RandomForestClassifier, X) -> np.ndarray:
    """森の中の木 1 本ずつの予測確率を (木の本数, 行数) の形で取り出す。"""
    return np.stack([tree.predict_proba(X)[:, 1] for tree in forest.estimators_])


def boosting_curve(model, X_test, y_test) -> list[tuple[int, float]]:
    """先頭 k 本だけを使った予測の ROC AUC（ブースティング＝足し算の途中経過）。"""
    return [(k, float(roc_auc_score(y_test, proba_at(model, X_test, k)))) for k in TREE_COUNTS]


def bagging_curve(probas: np.ndarray, y_test) -> list[tuple[int, float]]:
    """先頭 k 本の平均を取った予測の ROC AUC（バギング＝多数決・平均）。"""
    return [(k, float(roc_auc_score(y_test, probas[:k].mean(axis=0)))) for k in TREE_COUNTS]


def draw(path, boosting, bagging) -> None:
    """木の本数に対する ROC AUC の動きを 1 枚に並べる。"""
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.plot(
        [k for k, _ in boosting],
        [auc for _, auc in boosting],
        marker="o",
        color="#e45756",
        linewidth=2,
        label="ブースティング（LightGBM）",
    )
    ax.plot(
        [k for k, _ in bagging],
        [auc for _, auc in bagging],
        marker="s",
        color="#4c78a8",
        linewidth=2,
        label="バギング（ランダムフォレスト）",
    )
    ax.set_xscale("log")
    ax.set_xticks(TREE_COUNTS)
    ax.set_xticklabels([str(k) for k in TREE_COUNTS])
    ax.set_xlabel("使った木の本数（対数目盛）")
    ax.set_ylabel("評価データの ROC AUC")
    ax.set_title("木を増やしたときの動き ― ブースティングは途中で頭打ちになり下がる")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right")
    fig.tight_layout()
    OUT_DIR.mkdir(exist_ok=True)
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)

    booster = make_lgbm().fit(train, y_train)
    forest = RandomForestClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, n_jobs=1)
    forest.fit(train, y_train)
    probas = forest_probas(forest, test)

    boosting = boosting_curve(booster, test, y_test)
    bagging = bagging_curve(probas, y_test)

    print("■ 木を増やしたときの評価データの ROC AUC")
    print("本数 | ブースティング | バギング")
    for (k, boost_auc), (_, bag_auc) in zip(boosting, bagging):
        print(f"{k:>4} |     {boost_auc:.4f}     |  {bag_auc:.4f}")
    print()

    print("■ 読み取れること")
    print(f"ブースティング: 50 本 {dict(boosting)[50]:.4f} → 200 本 {dict(boosting)[200]:.4f}（増やすと下がった）")
    print(f"バギング      : 5 本 {dict(bagging)[5]:.4f} → 200 本 {dict(bagging)[200]:.4f}（増やすと落ち着く）")
    print()

    # バギングは「木ごとの確率の平均」そのもの。平均を取り直せば本数を減らした結果が作れる
    same = bool(np.allclose(probas.mean(axis=0), forest.predict_proba(test)[:, 1], atol=1e-9))
    print(f"森の予測は木ごとの確率の平均と一致するか: {same}")
    # ブースティングは「足し算の途中」を持っているので、先頭 50 本で打ち切れる
    print(f"先頭 50 本で打ち切った予測の ROC AUC: {dict(boosting)[50]:.4f}")

    path = OUT_DIR / "s19_boosting_vs_bagging.png"
    draw(path, boosting, bagging)
    print(f"図を保存しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
