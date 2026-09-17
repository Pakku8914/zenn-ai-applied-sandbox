"""線形モデルと木モデルを同じ条件で比べる（この章の結論は「線形が勝つ」）。

使い方:
    docker compose exec lab python src/session17/linear_vs_trees.py
"""

from __future__ import annotations

import lightgbm
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, roc_auc_score

from common import (
    N_ESTIMATORS,
    RANDOM_STATE,
    baseline_scores,
    fit_model,
    load_review_table,
    prepare,
    split_xy,
)


def scores_of(model, X_train, y_train, X_test, y_test) -> tuple[float, float]:
    """モデルを学習して (accuracy, ROC AUC) を返す。条件は全モデルで同じにする。"""
    model.fit(X_train, y_train)
    proba = model.predict_proba(X_test)[:, 1]
    return (
        float(accuracy_score(y_test, model.predict(X_test))),
        float(roc_auc_score(y_test, proba)),
    )


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)

    base = baseline_scores(y_test)
    rows = [("ベースライン（全部 高評価）", base["accuracy"], base["roc_auc"])]

    logistic = fit_model(train, y_train)
    rows.append(
        (
            "ロジスティック回帰",
            float(accuracy_score(y_test, logistic.predict(test))),
            float(roc_auc_score(y_test, logistic.predict_proba(test)[:, 1])),
        )
    )
    # 木モデルの中身はセッション18・19 で扱います。ここでは「同じ条件で測る相手」として使うだけです
    forest = RandomForestClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, n_jobs=1)
    rows.append(("ランダムフォレスト", *scores_of(forest, train, y_train, test, y_test)))
    booster = lightgbm.LGBMClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, verbose=-1)
    rows.append(("LightGBM", *scores_of(booster, train, y_train, test, y_test)))

    print(f"■ 同じ特徴量 {train.shape[1]} 列・同じ分割で 3 つのモデルを比べる")
    print("モデル                     | accuracy | ROC AUC")
    for label, accuracy, auc in rows:
        print(f"{label:<26} |  {accuracy:.4f}  | {auc:.4f}")
    print()

    ranking = sorted(rows[1:], key=lambda row: row[2], reverse=True)
    print("■ ROC AUC の順位")
    for rank, (label, _, auc) in enumerate(ranking, start=1):
        print(f"{rank} 位: {label}（{auc:.4f}）")
    print()
    print("いちばん単純なモデルが 1 位です。星は「価格・ページ数・本文の長さの足し算」で決まる構造なので、")
    print("直線（正確には超平面）で切るだけで十分に説明できます。木モデルはその斜めの境目を階段で")
    print("近似するため、同じデータ量では不利になります。")


if __name__ == "__main__":
    main()
