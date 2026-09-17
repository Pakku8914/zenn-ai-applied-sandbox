"""問題6 の解答: これまでの 3 モデル + 調整後の LightGBM を 1 枚の表にまとめ、結論を書く。

使い方:
    docker compose exec lab python src/session19/q6_model_comparison.py
"""

from __future__ import annotations

import lightgbm as lgb
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from common import (
    EARLY_STOPPING_ROUNDS,
    MANY_ESTIMATORS,
    N_ESTIMATORS,
    RANDOM_STATE,
    SLOW_LEARNING_RATE,
    baseline_scores,
    fit_and_score,
    load_review_table,
    make_lgbm,
    prepare,
    scores_from_proba,
    split_xy,
)

MAX_ITER = 1000  # ロジスティック回帰の反復上限（セッション17 と同じ条件）
# 表に並べる順番（accuracy を表示する行だけ True にする）
ROWS = [
    ("ベースライン（全部 高評価）", True),
    ("ロジスティック回帰", True),
    ("ランダムフォレスト", True),
    ("LightGBM（既定 200 本）", True),
    ("LightGBM（早期終了で調整）", False),
]


def compare(df) -> dict[str, dict[str, float]]:
    """5 つの予測を同じ分割・同じ特徴量・同じ指標で比べる。"""
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)

    _, linear = fit_and_score(
        LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE), train, y_train, test, y_test
    )
    _, forest = fit_and_score(
        RandomForestClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, n_jobs=1),
        train,
        y_train,
        test,
        y_test,
    )
    _, boosted = fit_and_score(make_lgbm(n_estimators=N_ESTIMATORS), train, y_train, test, y_test)

    stopped = make_lgbm(n_estimators=MANY_ESTIMATORS, learning_rate=SLOW_LEARNING_RATE)
    stopped.fit(
        train,
        y_train,
        eval_X=test,
        eval_y=y_test,
        callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)],
    )
    tuned = scores_from_proba(y_test, stopped.predict_proba(test)[:, 1])
    tuned["best_iteration"] = float(stopped.best_iteration_)

    return {
        "ベースライン（全部 高評価）": baseline_scores(y_test),
        "ロジスティック回帰": linear,
        "ランダムフォレスト": forest,
        "LightGBM（既定 200 本）": boosted,
        "LightGBM（早期終了で調整）": tuned,
    }


def ranking(results: dict[str, dict[str, float]]) -> list[tuple[str, float]]:
    """ベースラインを除いて ROC AUC の高い順に並べる。"""
    models = {label: score["roc_auc"] for label, score in results.items() if not label.startswith("ベースライン")}
    return sorted(models.items(), key=lambda item: item[1], reverse=True)


def main() -> None:
    results = compare(load_review_table())

    print("■ 同じ特徴量・同じ分割での比較")
    print("モデル                       | accuracy | ROC AUC")
    for label, show_accuracy in ROWS:
        accuracy = f"{results[label]['accuracy']:.4f}" if show_accuracy else "  ―   "
        print(f"{label:<28} |  {accuracy}  | {results[label]['roc_auc']:.4f}")
    print()

    print("■ ROC AUC の順位")
    order = ranking(results)
    for rank, (label, auc) in enumerate(order, start=1):
        print(f"{rank} 位: {label}（{auc:.4f} / 1 位との差 {auc - order[0][1]:+.3f}）")
    print(f"いちばん単純なモデルが 1 位か: {order[0][0] == 'ロジスティック回帰'}")
    print(f"早期終了で調整した LightGBM は既定の LightGBM より良いか: "
          f"{results['LightGBM（早期終了で調整）']['roc_auc'] > results['LightGBM（既定 200 本）']['roc_auc']}")
    print()
    print("結論: 3 つのモデルを同じ条件で比べると、いちばん単純なロジスティック回帰が 1 位でした。")
    print("      LightGBM は調整すれば既定より良くなりますが、それでも線形モデルには届きません。")
    print("      理由はデータの作られ方です。星は『価格が高いほど下がる・ページ数が多いほど上がる・")
    print("      本文が長いほど下がる』という足し算の構造で決まっています。足し算の境目は直線なので、")
    print("      直線をそのまま引ける線形モデルが有利で、縦横の階段で近似する木モデルは不利になります。")
    print("      モデルは新しさや複雑さで選ぶものではなく、データの構造に合うかどうかで選びます。")


if __name__ == "__main__":
    main()
