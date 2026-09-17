"""問題3 の解答: gain の重要度を表にして、split（分割回数）との違いを確かめる。

使い方:
    docker compose exec lab python src/session19/q3_gain_table.py
"""

from __future__ import annotations

import pandas as pd

from common import gain_importance, load_review_table, make_lgbm, prepare, split_xy

# 「この 2 つで説明が付いている」と言えるかを確かめるための本数
TOP_N = 2


def build_table(df) -> pd.DataFrame:
    """既定パラメータの LightGBM を学習し、gain の大きい順に重要度を並べる。"""
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    model = make_lgbm(importance_type="gain").fit(train, y_train)
    return gain_importance(model, names)


def top_share(table: pd.DataFrame, top_n: int = TOP_N) -> float:
    """gain の合計に対して上位 top_n 列が占める割合を返す。"""
    return float(table["gain"].head(top_n).sum() / table["gain"].sum())


def main() -> None:
    table = build_table(load_review_table())

    print("■ gain で並べた重要度")
    print("順位 | 特徴量            | gain")
    # 小さな gain は丸め方で ±1 変わるので、表示は int()（切り捨て）で統一する
    for rank, row in enumerate(table.itertuples(index=False), start=1):
        print(f"{rank:>3}  | {row.feature:<17} | {int(row.gain):>9,}")
    print()

    print("■ 判定")
    print(f"上位 {TOP_N} 列: {list(table['feature'].head(TOP_N))}")
    print(f"上位 {TOP_N} 列が gain 合計に占める割合: {top_share(table):.0%}")
    category_share = table[table["feature"].str.startswith("category_")]["gain"].sum() / table["gain"].sum()
    print(f"カテゴリを開いた 5 列が gain 合計に占める割合: {category_share:.0%}")
    split_order = list(table.sort_values("split", ascending=False)["feature"])
    print(f"split（分割回数）で並べ替えたときの 1 位: {split_order[0]}")
    print(f"gain の順位と split の順位が同じか: {split_order == list(table['feature'])}")
    print()
    print("説明: gain は『その列で分けたときにどれだけ迷いが減ったか』の合計、split は『何回使われたか』の回数です。")
    print("      値の種類が多い列（単価や本文の長さ）は分け方の候補も多いので、どちらの指標でも上に来やすくなります。")
    print("      重要度が大きいことは『効いている』の証拠にはなりますが、『原因である』の証拠にはなりません。")
    print("      published_year はセッション16 の検定で p 値 0.2425 ＝ 有意でない列でした。重要度が 0 でなくても")
    print("      『関係がある』と言い切ってはいけません（この話はセッション26 の SHAP でもう一度扱います）。")


if __name__ == "__main__":
    main()
