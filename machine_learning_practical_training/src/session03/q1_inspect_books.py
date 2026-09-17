"""問題1 の解答: books.csv を読み込み、形と型を確認する。

使い方:
    docker compose exec lab python src/session03/q1_inspect_books.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def main() -> None:
    books = pd.read_csv(DATA_DIR / "books.csv")

    print(f"books.csv : {books.shape[0]} 行 × {books.shape[1]} 列")
    print(f"列名      : {list(books.columns)}")

    print("\n■ 列ごとの dtype")
    print(books.dtypes)

    # dtype は文字列に変換して比べる（表示そのままの名前で判定できる）
    str_cols = [c for c in books.columns if str(books[c].dtype) == "str"]
    int_cols = [c for c in books.columns if str(books[c].dtype) == "int64"]
    missing_cols = [c for c in books.columns if bool(books[c].isna().any())]

    print(f"\n文字列（str）の列 : {str_cols}")
    print(f"整数（int64）の列 : {int_cols}")
    print(f"欠損がある列      : {missing_cols}")


if __name__ == "__main__":
    main()
