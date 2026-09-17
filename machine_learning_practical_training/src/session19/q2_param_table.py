"""問題2 の解答: n_estimators と learning_rate の 4 通りを表にして、既定値の位置を確かめる。

使い方:
    docker compose exec lab python src/session19/q2_param_table.py
"""

from __future__ import annotations

import pandas as pd

from common import fit_and_score, load_review_table, make_lgbm, prepare, split_xy

# 手で試す組み合わせ（体系的な探索はセッション23）
N_ESTIMATORS_LIST = [50, 200]
LEARNING_RATE_LIST = [0.05, 0.1]
# 既定の組み合わせ（この章の出発点）
DEFAULT_COMBINATION = (200, 0.1)
# 比べる相手（セッション17 で実測したロジスティック回帰の ROC AUC）
LINEAR_ROC_AUC = 0.8265


def build_table(df) -> pd.DataFrame:
    """4 通りを同じ分割・同じ前処理で学習し、決まった順番に並べた表を返す。

    ROC AUC で並べ替えないのは、同じ 0.8110 に見える 2 行の順序が実行ごとに紛れないようにするためです。
    """
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    rows = []
    for n_estimators in N_ESTIMATORS_LIST:
        for learning_rate in LEARNING_RATE_LIST:
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


def rank_of(table: pd.DataFrame, combination: tuple[int, float]) -> int:
    """ROC AUC で見たときの順位を返す（1 が最良）。並べ替えずに「自分より上が何行あるか」で数える。"""
    matched = table[
        (table["n_estimators"] == combination[0]) & (table["learning_rate"] == combination[1])
    ]
    target = float(matched["roc_auc"].iloc[0])
    return int((table["roc_auc"] > target).sum()) + 1


def main() -> None:
    table = build_table(load_review_table())

    print("■ 4 通りの組み合わせ（n_estimators × learning_rate）")
    print("n_estimators | learning_rate | accuracy | ROC AUC")
    for row in table.itertuples(index=False):
        print(f"{row.n_estimators:>12} | {row.learning_rate:>13} |  {row.accuracy:.4f}  | {row.roc_auc:.4f}")
    print()

    print("■ 判定")
    print(f"既定の組み合わせ（{DEFAULT_COMBINATION[0]} 本・lr {DEFAULT_COMBINATION[1]}）の順位: "
          f"{rank_of(table, DEFAULT_COMBINATION)} 位 / {len(table)} 通り")
    print(f"最良と最悪の差: {table['roc_auc'].max() - table['roc_auc'].min():+.3f}")
    print(f"いちばん良い組み合わせでもロジスティック回帰（{LINEAR_ROC_AUC:.4f}）に届いたか: "
          f"{table['roc_auc'].max() > LINEAR_ROC_AUC}")
    print()
    print("説明: 木を増やすことと学習率を上げることは、どちらも『修正を強くする』方向の操作です。")
    print("      強い修正を長く続けたのが既定値の組み合わせで、この小さなデータでは行き過ぎでした。")
    print("      本数を減らす・学習率を下げるのどちらでも改善しますが、両方を弱めると今度は足りません。")


if __name__ == "__main__":
    main()
