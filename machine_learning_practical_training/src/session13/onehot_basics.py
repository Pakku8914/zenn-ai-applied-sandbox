"""One-Hot エンコーディングの基本。列の名前・列数・行ごとに立つ 1 の数を確かめる。

使い方:
    docker compose exec lab python src/session13/onehot_basics.py
"""

from __future__ import annotations

import pandas as pd
from sklearn.preprocessing import OneHotEncoder

from common import MISSING_LABEL, load_books, load_customers

SAMPLE = ["技術書", "小説", "実用書"]


def main() -> None:
    books = load_books()

    # 引数は必ず明示する（版によって既定値が変わるため。本書の規約）
    encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    encoder.fit(books[["category"]])
    print("■ 5 水準の category を 3 行だけ変換してみる")
    print(f"列の並び : {' / '.join(encoder.categories_[0])}")
    for value, row in zip(SAMPLE, encoder.transform(pd.DataFrame({"category": SAMPLE}))):
        print(f"{value:>4} → {[int(v) for v in row]}")
    print(f"列の名前 : {' / '.join(encoder.get_feature_names_out(['category']))}")
    print()

    customers = load_customers()
    print("■ 欠損を埋めずに開くと、NaN が 1 つの水準になる")
    raw = OneHotEncoder(sparse_output=False, handle_unknown="ignore").fit(customers[["region"]])
    print(f"region の水準の数         : {len(raw.categories_[0])}")
    print(f"最後の水準が欠損（NaN）か : {bool(pd.isna(raw.categories_[0][-1]))}")
    print()

    # 欠損を「不明」で埋めてから開く。こうすると列名を見ただけで中身が分かる
    filled = customers.copy()
    filled["region"] = filled["region"].fillna(MISSING_LABEL)
    two = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    encoded = two.fit_transform(filled[["region", "channel"]])
    print("■ region（欠損を「不明」で埋めて 8 水準）と channel（4 水準）を開く")
    print(f"入力 : {filled[['region', 'channel']].shape[1]} 列 → 出力 : {encoded.shape[1]} 列")
    print(f"列名 : {' / '.join(two.get_feature_names_out(['region', 'channel']))}")
    print(f"1 行あたりに立つ 1 の数            : {int(encoded[0].sum())}")
    print(f"すべての行で 1 の合計が 2 になるか : {bool((encoded.sum(axis=1) == 2).all())}")


if __name__ == "__main__":
    main()
