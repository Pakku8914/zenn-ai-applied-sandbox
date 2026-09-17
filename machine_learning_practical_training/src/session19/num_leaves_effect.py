"""num_leaves を変えると木の形と当てはまりがどう変わるかを確かめる。

葉ごと成長（leaf-wise）の LightGBM では、木の複雑さを決めるのは深さではなく葉の数です。
max_depth を付けたときに葉の数がどう抑えられるかも一緒に見ます。

使い方:
    docker compose exec lab python src/session19/num_leaves_effect.py
"""

from __future__ import annotations

import pandas as pd

from common import (
    load_review_table,
    make_lgbm,
    prepare,
    scores_from_proba,
    split_xy,
    tree_leaf_counts,
)

# 試す葉の数（31 が LightGBM の既定値）
LEAF_SETTINGS = [7, 31, 127]
# 深さの上限を付けたときの比較用（葉ごと成長でも 2 の深さ乗が上限になる）
CAPPED = {"num_leaves": 31, "max_depth": 3}


def build_table(train, y_train, test, y_test) -> pd.DataFrame:
    """num_leaves ごとに「訓練データの AUC・評価データの AUC・実際の葉の数」を並べる。"""
    rows = []
    for num_leaves in LEAF_SETTINGS:
        model = make_lgbm(num_leaves=num_leaves).fit(train, y_train)
        leaves = tree_leaf_counts(model)
        rows.append(
            {
                "num_leaves": num_leaves,
                "max_depth": -1,
                "train_auc": scores_from_proba(y_train, model.predict_proba(train)[:, 1])["roc_auc"],
                "test_auc": scores_from_proba(y_test, model.predict_proba(test)[:, 1])["roc_auc"],
                "max_leaves_in_tree": max(leaves),
            }
        )

    capped = make_lgbm(**CAPPED).fit(train, y_train)
    capped_leaves = tree_leaf_counts(capped)
    rows.append(
        {
            "num_leaves": CAPPED["num_leaves"],
            "max_depth": CAPPED["max_depth"],
            "train_auc": scores_from_proba(y_train, capped.predict_proba(train)[:, 1])["roc_auc"],
            "test_auc": scores_from_proba(y_test, capped.predict_proba(test)[:, 1])["roc_auc"],
            "max_leaves_in_tree": max(capped_leaves),
        }
    )
    return pd.DataFrame(rows)


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    table = build_table(train, y_train, test, y_test)

    print("■ num_leaves と木の形（n_estimators = 200・learning_rate = 0.1 は固定）")
    print("num_leaves | max_depth | 訓練 AUC | 評価 AUC | 木 1 本の葉の数の最大")
    for row in table.itertuples(index=False):
        print(
            f"{row.num_leaves:>10} | {row.max_depth:>9} |  {row.train_auc:.4f}  |  {row.test_auc:.4f}  |"
            f" {row.max_leaves_in_tree:>3} 枚"
        )
    print()

    grown = table[table["max_depth"] == -1]
    print("■ 読み取り方")
    print("・葉を増やすほど訓練データの AUC は上がります（表現力が増えるので必ず上がります）")
    print("・評価データの AUC が同じように上がるとは限りません。上の表で自分の目で確かめてください")
    print(f"・深さの上限を 3 にすると、葉は 2 の 3 乗 = 8 枚までに抑えられます（実測 {int(table.iloc[-1]['max_leaves_in_tree'])} 枚）")
    print(f"・訓練 AUC は葉 {int(grown['num_leaves'].max())} のときが葉 {int(grown['num_leaves'].min())} のときより高いか: "
          f"{bool(grown['train_auc'].iloc[-1] > grown['train_auc'].iloc[0])}")


if __name__ == "__main__":
    main()
