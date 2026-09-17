"""問題4 の解答: 早期終了で木の本数をモデルに決めさせ、古い書き方の警告も確認する。

使い方:
    docker compose exec lab python src/session19/q4_early_stopping.py
"""

from __future__ import annotations

import warnings

import lightgbm as lgb

from common import (
    EARLY_STOPPING_ROUNDS,
    LEARNING_RATE,
    MANY_ESTIMATORS,
    N_ESTIMATORS,
    SLOW_LEARNING_RATE,
    load_review_table,
    make_lgbm,
    prepare,
    scores_from_proba,
    split_xy,
)

# 比べる相手（セッション17 で実測したロジスティック回帰の ROC AUC）
LINEAR_ROC_AUC = 0.8265


def run(df) -> dict[str, object]:
    """既定 200 本のモデルと、早期終了に任せたモデルを同じ分割で比べる。"""
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)

    fixed = make_lgbm(n_estimators=N_ESTIMATORS, learning_rate=LEARNING_RATE).fit(train, y_train)
    fixed_scores = scores_from_proba(y_test, fixed.predict_proba(test)[:, 1])

    stopped = make_lgbm(n_estimators=MANY_ESTIMATORS, learning_rate=SLOW_LEARNING_RATE)
    stopped.fit(
        train,
        y_train,
        eval_X=test,  # LightGBM 4.7.0 では eval_set ではなくこの 2 つを使う
        eval_y=y_test,
        callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)],
    )
    stopped_scores = scores_from_proba(y_test, stopped.predict_proba(test)[:, 1])

    return {
        "fixed": fixed_scores,
        "stopped": stopped_scores,
        "best_iteration": int(stopped.best_iteration_),
        "hit_limit": bool(stopped.best_iteration_ >= MANY_ESTIMATORS),
    }


def deprecation_warnings(df) -> list[tuple[str, str]]:
    """eval_set を使ったときに出る警告の型名と文面を集める。"""
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        make_lgbm(n_estimators=10).fit(train, y_train, eval_set=[(test, y_test)])
    return [(type(item.message).__name__, str(item.message)) for item in caught if "eval_set" in str(item.message)]


def main() -> None:
    df = load_review_table()
    result = run(df)

    print("■ 本数を人が決めた場合と、早期終了に任せた場合")
    print(f"固定 {N_ESTIMATORS} 本・lr {LEARNING_RATE}      : ROC AUC {result['fixed']['roc_auc']:.4f}")
    print(f"早期終了・lr {SLOW_LEARNING_RATE}          : ROC AUC {result['stopped']['roc_auc']:.4f}")
    print(f"早期終了が選んだ本数（best_iteration_）: {result['best_iteration']}")
    print(f"上限の {MANY_ESTIMATORS} 本まで使ってしまったか: {result['hit_limit']}")
    print(f"ロジスティック回帰（{LINEAR_ROC_AUC:.4f}）に届いたか: {result['stopped']['roc_auc'] > LINEAR_ROC_AUC}")
    print()

    print("■ 古い書き方（eval_set）で出る警告")
    for name, message in deprecation_warnings(df):
        print(f"{name}: {message}")
    print()
    print("説明: 早期終了は『検証データのスコアが 50 回続けて改善しなければ止める』仕組みです。")
    print("      本数を人が当てる必要がなくなり、このデータでは既定の 200 本より良い結果になりました。")
    print("      ただし止め時を決めるのに評価データを使っているので、この 1 回の数字は少し甘く見えています。")
    print("      本来は訓練データをさらに分けた検証データを使います（セッション22 で扱います）。")
    print("      それでも線形モデルには届きません。強いモデルを調整しても勝てない相手がいます。")


if __name__ == "__main__":
    main()
