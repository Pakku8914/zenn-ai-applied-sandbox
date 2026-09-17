"""Series と DataFrame の違いと、インデックスの役割を確かめる。

使い方:
    docker compose exec lab python src/session03/series_and_frame.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def main() -> None:
    # 1. Series は「ラベル付きの 1 列」
    price = pd.Series([1410, 3200, 880], index=["B0001", "B0002", "B0003"], name="price")
    print("■ Series（手で作った 3 行の例）")
    print(price)
    print(f"ラベルで取り出す price['B0002'] : {price['B0002']}")
    print(f"位置で取り出す   price.iloc[1]  : {price.iloc[1]}")
    print(f"インデックスの中身             : {price.index.tolist()}")

    # 2. DataFrame は「同じインデックスを共有する Series の束」
    df = pd.DataFrame(
        {"price": [1410, 3200, 880], "pages": [240, 520, 180]},
        index=["B0001", "B0002", "B0003"],
    )
    print("\n■ DataFrame（手で作った 3 行 2 列の例）")
    print(df)
    print(f"df['price'] の型   : {type(df['price']).__name__}")
    print(f"df[['price']] の型 : {type(df[['price']]).__name__}")

    # 3. 実データを読むと、インデックスは 0 から始まる行番号（RangeIndex）になる
    books = pd.read_csv(DATA_DIR / "books.csv")
    print("\n■ books.csv")
    print(f"形                 : {books.shape[0]} 行 × {books.shape[1]} 列")
    print(f"列名               : {list(books.columns)}")
    print(f"インデックスの型   : {type(books.index).__name__}")
    print(f"先頭 3 つのラベル  : {books.index[:3].tolist()}")

    # 4. 意味のある列をインデックスにすると、ラベルで 1 行を引ける
    #    inplace=True は使わず、返り値を新しい変数で受け取る（本書共通の書き方）
    indexed = books.set_index("book_id")
    print(f"\nset_index 後のインデックス名 : {indexed.index.name}")
    print(f"B0001 の price               : {indexed.loc['B0001', 'price']}")
    print(f"元の books は変わっていない  : {list(books.columns)}")


if __name__ == "__main__":
    main()
