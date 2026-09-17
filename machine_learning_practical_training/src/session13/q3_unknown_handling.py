"""問題3 の解答: 未知のカテゴリが来たときの挙動を 3 通り試し、件数も数える。

使い方:
    docker compose exec lab python src/session13/q3_unknown_handling.py
"""

from __future__ import annotations

import pandas as pd
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder

from common import load_books

UNKNOWN = "写真集"
KNOWN = "技術書"


def main() -> None:
    known = load_books()[["category"]]
    new_rows = pd.DataFrame({"category": [UNKNOWN, KNOWN]})

    ignore = OneHotEncoder(sparse_output=False, handle_unknown="ignore").fit(known)
    strict = OneHotEncoder(sparse_output=False, handle_unknown="error").fit(known)
    ordinal = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1).fit(known)

    print("■ 訓練データで覚えた水準")
    print(" / ".join(ignore.categories_[0]))
    print()

    print("■ 変換の結果")
    for value, one_hot, code in zip(
        new_rows["category"], ignore.transform(new_rows), ordinal.transform(new_rows)
    ):
        print(f"{value} : One-Hot {[int(v) for v in one_hot]}（合計 {int(one_hot.sum())}）/ Ordinal {int(code[0])}")
    try:
        strict.transform(new_rows)
    except ValueError as error:
        print(f'handle_unknown="error" : {type(error).__name__}: {error}')
    print()

    print("■ 未知の行を自分で数える（エラーも警告も出ないため）")
    is_unknown = ~new_rows["category"].isin(ignore.categories_[0])
    print(f"未知の行数 : {int(is_unknown.sum())} / {len(new_rows)}")
    print(f"未知だった値 : {' / '.join(new_rows.loc[is_unknown, 'category'])}")
    print()

    print("■ 全て 0 のベクトルが意味すること")
    print("「どの水準にも当てはまらない行」として扱われます。学習した 5 つの水準のどれでもないので、")
    print("モデルはカテゴリの情報なしで判断します。エラーは出ないので、未知の件数は別に数えて監視します。")


if __name__ == "__main__":
    main()
