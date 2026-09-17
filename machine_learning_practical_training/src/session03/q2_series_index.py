"""問題2 の解答: Series と DataFrame、インデックスの役割を確かめる。

使い方:
    docker compose exec lab python src/session03/q2_series_index.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def main() -> None:
    # 1. 辞書から Series を作ると、キーがインデックスになる
    series = pd.Series({"B0001": 1410, "B0002": 3200, "B0003": 880})
    print("■ 手で作った Series")
    print(series)
    print(f"インデックス       : {series.index.tolist()}")
    print(f"ラベルで引く .loc  : {series.loc['B0002']}")
    print(f"位置で引く .iloc   : {series.iloc[0]}")

    # 2. DataFrame から 1 列を取り出すと Series になる
    df = pd.DataFrame({"price": series, "pages": pd.Series({"B0001": 240, "B0002": 520, "B0003": 180})})
    print("\n■ 2 つの Series を並べた DataFrame")
    print(df)
    print(f"df['price'] の型   : {type(df['price']).__name__}")
    print(f"df[['price']] の型 : {type(df[['price']]).__name__}")

    # 3. 実データのインデックスを book_id に付け替える（返り値を受け取る）
    books = pd.read_csv(DATA_DIR / "books.csv")
    indexed = books.set_index("book_id")
    restored = indexed.reset_index()

    print("\n■ books のインデックス操作")
    print(f"読み込んだ直後の列数     : {books.shape[1]} 列（インデックスは {type(books.index).__name__}）")
    print(f"set_index 後の列数       : {indexed.shape[1]} 列（インデックス名は {indexed.index.name}）")
    print(f"reset_index で戻した列数 : {restored.shape[1]} 列")
    print(f"B0001 の price           : {indexed.loc['B0001', 'price']}")
    print(f"元の books は無傷か      : {'book_id' in books.columns}")


if __name__ == "__main__":
    main()
