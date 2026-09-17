"""訓練データに無いカテゴリが来たときの挙動を handle_unknown で切り替えて確かめる。

使い方:
    docker compose exec lab python src/session13/unknown_category.py
"""

from __future__ import annotations

import pandas as pd
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder

from common import load_books

UNKNOWN = "写真集"  # 来月から取り扱いが始まるジャンル。訓練データには 1 冊も無い


def main() -> None:
    known = load_books()[["category"]]
    new_rows = pd.DataFrame({"category": [UNKNOWN, "技術書"]})

    print("■ 訓練データで覚えた水準")
    ignore = OneHotEncoder(sparse_output=False, handle_unknown="ignore").fit(known)
    print(f"categories_ : {' / '.join(ignore.categories_[0])}")
    print()

    print(f"■ 未知のカテゴリ「{UNKNOWN}」を変換する")
    for value, row in zip(new_rows["category"], ignore.transform(new_rows)):
        print(f'handle_unknown="ignore" : {value} → {[int(v) for v in row]}（合計 {int(row.sum())}）')

    strict = OneHotEncoder(sparse_output=False, handle_unknown="error").fit(known)
    try:
        strict.transform(new_rows)
    except ValueError as error:
        print(f'handle_unknown="error"  : {type(error).__name__}: {error}')
    print()

    print("■ OrdinalEncoder なら「未知」に専用の番号を割り当てられる")
    ordinal = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1).fit(known)
    pairs = " / ".join(f"{name}={code}" for code, name in enumerate(ordinal.categories_[0]))
    print(f"番号の付き方 : {pairs}")
    for value, row in zip(new_rows["category"], ordinal.transform(new_rows)):
        print(f"{value} → {int(row[0])}")


if __name__ == "__main__":
    main()
