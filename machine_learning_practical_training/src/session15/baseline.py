"""ベースライン（多数クラス予測）を先に置いてから、最初のモデルと比べる。

使い方:
    docker compose exec lab python src/session15/baseline.py
"""

from __future__ import annotations

from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression

from common import (
    MAX_ITER,
    RANDOM_STATE,
    fit_and_score,
    load_review_features,
    pad,
    pipeline_for,
    split_features,
)


def main() -> None:
    X_train, X_test, y_train, y_test = split_features(load_review_features())

    print("■ ベースラインを先に置く（高評価レビューの分類）")
    print(f"訓練 {len(X_train):,} 件 / 評価 {len(X_test):,} 件 / 評価データの正例率 {y_test.mean():.4f}")
    print()

    # ベースラインは特徴量を見ないが、条件をそろえるため同じ Pipeline に載せる
    dummy = DummyClassifier(strategy="most_frequent", random_state=RANDOM_STATE)
    logistic = LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)
    base = fit_and_score(dummy, X_train, y_train, X_test, y_test)
    model = fit_and_score(logistic, X_train, y_train, X_test, y_test)

    print(f"{pad('モデル')} | accuracy | ROC AUC")
    for label, score in [("ベースライン（多数クラス）", base), ("ロジスティック回帰", model)]:
        print(f"{pad(label)} |   {score['accuracy']:.4f} |  {score['roc_auc']:.4f}")
    print()

    print("■ ベースラインの中身を確かめる")
    predicted = pipeline_for(dummy).fit(X_train, y_train).predict(X_test)
    print(f"評価データの予測がすべて「高評価（1）」か : {bool((predicted == 1).all())}")
    print(f"accuracy が評価データの正例率と一致するか : {round(base['accuracy'], 4) == round(float(y_test.mean()), 4)}")
    print(f"ROC AUC がちょうど 0.5000 か : {round(base['roc_auc'], 4) == 0.5}")
    print()

    print("■ 改善幅（ベースラインを引いた値）")
    print(f"accuracy : {model['accuracy'] - base['accuracy']:+.4f}")
    print(f"ROC AUC  : {model['roc_auc'] - base['roc_auc']:+.4f}")
    print(f"ロジスティック回帰の log loss : {model['log_loss']:.4f}")
    # ベースラインは確率 1.0 を返すので、外した行の罰がきわめて大きくなる
    print(f"ベースラインの log loss のほうが大きいか : {base['log_loss'] > model['log_loss']}")


if __name__ == "__main__":
    main()
