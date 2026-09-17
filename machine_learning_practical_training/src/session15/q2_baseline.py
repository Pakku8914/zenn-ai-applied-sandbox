"""問題2 の解答：ベースラインを 2 種類作り、モデルの改善幅を測る。

使い方:
    docker compose exec lab python src/session15/q2_baseline.py
"""

from __future__ import annotations

from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss, roc_auc_score

from common import MAX_ITER, RANDOM_STATE, load_review_features, pad, pipeline_for, split_features


def evaluate(model, X_train, y_train, X_eval, y_eval) -> dict[str, float | bool]:
    """学習して、accuracy・ROC AUC・log loss をまとめて返す（自分で書く）。"""
    pipeline = pipeline_for(model).fit(X_train, y_train)
    predicted = pipeline.predict(X_eval)
    proba = pipeline.predict_proba(X_eval)[:, 1]
    return {
        "accuracy": float(accuracy_score(y_eval, predicted)),
        "roc_auc": float(roc_auc_score(y_eval, proba)),
        "log_loss": float(log_loss(y_eval, proba)),
        "all_positive": bool((predicted == 1).all()),
    }


def main() -> None:
    X_train, X_test, y_train, y_test = split_features(load_review_features())
    print(f"評価データ {len(X_test):,} 件 / 正例率 {y_test.mean():.4f}")
    print()

    most_frequent = DummyClassifier(strategy="most_frequent", random_state=RANDOM_STATE)
    always_low = DummyClassifier(strategy="constant", constant=0, random_state=RANDOM_STATE)
    logistic = LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)

    scores = {}
    print(f"{pad('モデル', 28)} | accuracy | ROC AUC")
    for label, model in [
        ("ベースライン（多数クラス）", most_frequent),
        ("ベースライン（全員を低評価）", always_low),
        ("ロジスティック回帰", logistic),
    ]:
        scores[label] = evaluate(model, X_train, y_train, X_test, y_test)
        print(f"{pad(label, 28)} |   {scores[label]['accuracy']:.4f} |  {scores[label]['roc_auc']:.4f}")
    print()

    base = scores["ベースライン（多数クラス）"]
    low = scores["ベースライン（全員を低評価）"]
    model = scores["ロジスティック回帰"]

    print("■ ベースラインの性質を確かめる")
    print(f"多数クラス予測がすべて「高評価（1）」か : {base['all_positive']}")
    print(f"その accuracy が評価データの正例率と一致するか : "
          f"{round(base['accuracy'], 4) == round(float(y_test.mean()), 4)}")
    print(f"2 つのベースラインの accuracy を足すと 1 になるか : "
          f"{round(base['accuracy'] + low['accuracy'], 6) == 1.0}")
    print(f"どちらのベースラインも ROC AUC が 0.5000 か : "
          f"{round(base['roc_auc'], 4) == round(low['roc_auc'], 4) == 0.5}")
    print()

    print("■ 改善幅（多数クラス予測を引いた値）")
    print(f"accuracy : {model['accuracy'] - base['accuracy']:+.4f}")
    print(f"ROC AUC  : {model['roc_auc'] - base['roc_auc']:+.4f}")
    print(f"ロジスティック回帰の log loss : {model['log_loss']:.4f}")
    print(f"accuracy の改善が 0.03 未満か : {model['accuracy'] - base['accuracy'] < 0.03}")
    print()

    print("■ accuracy だけで報告してはいけない理由")
    print("正例が 8 割を占めるデータでは、何も学習せず全員を「高評価」と答えるだけで")
    print("accuracy が 0.8168 になります。0.8422 という数字は立派に見えますが、")
    print("当て推量に対する上積みは 0.0254 しかありません。順位づけの力を見る ROC AUC なら")
    print("0.5000 と 0.8265 で、モデルが学習したことがはっきり分かります。")


if __name__ == "__main__":
    main()
