"""問題6 の解答: 3 つのモデルを同じ条件で比べ、「なぜ線形が勝つのか」を根拠つきで書く。

使い方:
    docker compose exec lab python src/session17/q6_model_choice_report.py
"""

from __future__ import annotations

import lightgbm
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score

from common import (
    MAX_ITER,
    N_ESTIMATORS,
    RANDOM_STATE,
    baseline_scores,
    coefficient_table,
    fit_model,
    load_review_table,
    prepare,
    split_xy,
)

# 「星は足し算で決まっている」という仮説から予想される係数の符号
EXPECTED_SIGNS = {"unit_price": -1, "pages": +1, "body_length": -1}


def evaluate(model, X_train, y_train, X_test, y_test) -> dict[str, float]:
    """どのモデルでも同じ手順で accuracy と ROC AUC を測る。"""
    model.fit(X_train, y_train)
    return {
        "accuracy": float(accuracy_score(y_test, model.predict(X_test))),
        "roc_auc": float(roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])),
    }


def compare(df) -> dict[str, dict[str, float]]:
    """ベースラインと 3 つのモデルを同じ分割・同じ特徴量で比べる。"""
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    return {
        "ベースライン": baseline_scores(y_test),
        "ロジスティック回帰": evaluate(
            LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE),
            train,
            y_train,
            test,
            y_test,
        ),
        "ランダムフォレスト": evaluate(
            RandomForestClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, n_jobs=1),
            train,
            y_train,
            test,
            y_test,
        ),
        "LightGBM": evaluate(
            lightgbm.LGBMClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, verbose=-1),
            train,
            y_train,
            test,
            y_test,
        ),
    }


def sign_check(df) -> dict[str, bool]:
    """仮説どおりの符号になっているかを列ごとに確かめる。"""
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    table = coefficient_table(fit_model(train, y_train), names)
    coefs = dict(zip(table["feature"], table["coef"]))
    return {name: bool(np.sign(coefs[name]) == sign) for name, sign in EXPECTED_SIGNS.items()}


def main() -> None:
    df = load_review_table()
    results = compare(df)

    print("■ 同じ特徴量・同じ分割での比較")
    print("モデル                     | accuracy | ROC AUC")
    for label, score in results.items():
        print(f"{label:<26} |  {score['accuracy']:.4f}  | {score['roc_auc']:.4f}")
    print()

    models = {k: v for k, v in results.items() if k != "ベースライン"}
    ranking = sorted(models.items(), key=lambda item: item[1]["roc_auc"], reverse=True)
    print("■ ROC AUC の順位と、1 位との差")
    top_auc = ranking[0][1]["roc_auc"]
    for rank, (label, score) in enumerate(ranking, start=1):
        print(f"{rank} 位: {label}（{score['roc_auc']:.4f} / 1 位との差 {score['roc_auc'] - top_auc:+.4f}）")
    print(f"いちばん単純なモデルが 1 位か: {ranking[0][0] == 'ロジスティック回帰'}")
    print()

    print("■ 仮説どおりの符号になっているか（正 = 高評価に効く / 負 = 逆に効く）")
    for name, ok in sign_check(df).items():
        print(f"{name}: 予想 {EXPECTED_SIGNS[name]:+d} / 一致したか {ok}")
    print()
    print("判断: 星は「価格が高いほど下がる・ページ数が多いほど上がる・レビュー本文が長いほど下がる」という")
    print("      足し算の構造で決まっています。足し算で決まる境目は直線（超平面）なので、線形モデルがそのまま")
    print("      当てはまります。木モデルは同じ境目を縦横の階段で近似するしかなく、境目の近くで無駄な分割が")
    print("      増えます。その分だけノイズを拾い、汎化性能が落ちました。")
    print("      → モデルの複雑さは「データの構造に合っているか」で選ぶものであり、新しさでは選びません。")


if __name__ == "__main__":
    main()
