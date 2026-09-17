"""問題1 の解答: 木を増やしたときの ROC AUC を、ブースティングとバギングで並べる。

使い方:
    docker compose exec lab python src/session19/q1_tree_count_curve.py
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

from common import N_ESTIMATORS, RANDOM_STATE, load_review_table, make_lgbm, prepare, proba_at, split_xy

# 何本目までを使った時点で測るか
TREE_COUNTS = [1, 5, 20, 50, 200]


def boosting_auc(model, X_test, y_test) -> dict[int, float]:
    """先頭 k 本だけを使った予測の ROC AUC。学習は 1 回だけで済む（足し算の途中経過が残っている）。"""
    return {k: float(roc_auc_score(y_test, proba_at(model, X_test, k))) for k in TREE_COUNTS}


def bagging_auc(forest, X_test, y_test) -> dict[int, float]:
    """先頭 k 本の確率を平均した予測の ROC AUC。バギングは平均なので後から本数を減らせる。"""
    probas = np.stack([tree.predict_proba(X_test)[:, 1] for tree in forest.estimators_])
    return {k: float(roc_auc_score(y_test, probas[:k].mean(axis=0))) for k in TREE_COUNTS}


def curves(df) -> tuple[dict[int, float], dict[int, float]]:
    """ブースティングとバギングの 2 本の曲線を返す。"""
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    booster = make_lgbm().fit(train, y_train)
    forest = RandomForestClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, n_jobs=1)
    forest.fit(train, y_train)
    return boosting_auc(booster, test, y_test), bagging_auc(forest, test, y_test)


def main() -> None:
    boosting, bagging = curves(load_review_table())

    print("■ 木の本数と評価データの ROC AUC")
    print("本数 | ブースティング（LightGBM） | バギング（ランダムフォレスト）")
    for k in TREE_COUNTS:
        print(f"{k:>4} |           {boosting[k]:.4f}          |          {bagging[k]:.4f}")
    print()

    print("■ 判定")
    print(f"ブースティングは 50 本より 200 本のほうが悪いか: {boosting[50] > boosting[200]}")
    print(f"バギングは 5 本より 200 本のほうが良いか: {bagging[200] > bagging[5]}")
    print()
    print("説明: ブースティングは前の木の誤りを次の木が修正します。修正の相手は訓練データの誤りなので、")
    print("      続けるほど訓練データに寄っていき、ある本数を超えると評価データでは悪くなります。")
    print("      バギングはばらつきを平均でならす仕組みなので、本数を増やしても悪くなりません。")
    print("      つまり『本数』の意味が 2 つの手法で違います。ブースティングでは本数が強さそのものです。")


if __name__ == "__main__":
    main()
