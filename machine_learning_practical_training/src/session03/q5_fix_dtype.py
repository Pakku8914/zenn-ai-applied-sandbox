"""問題5 の解答: 数値が文字列として読まれた事故を再現し、2 通りの方法で直す。

使い方:
    docker compose exec lab python src/session03/q5_fix_dtype.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
BOOKS_CSV = DATA_DIR / "books.csv"


def main() -> None:
    # 1. 事故の再現：price を文字列として読み込んでしまった
    bad = pd.read_csv(BOOKS_CSV, dtype={"price": "str"})
    print("■ 事故の再現（price を文字列として読んだ）")
    print(f"dtype         : {bad['price'].dtype}")
    print(f"1 行目の price: {bad['price'].iloc[0]!r}")
    print(f"price * 2     : {(bad['price'] * 2).iloc[0]!r}  ← 計算ではなく連結")
    try:
        bad["price"].mean()
        print("mean()        : 計算できてしまいました（想定外です）")
    except TypeError:
        print("mean()        : TypeError（文字列の平均は計算できない）")

    # 2. 直し方その 1：読み込みをやり直す（原因に一番近いところで直す）
    good = pd.read_csv(BOOKS_CSV, dtype={"price": "int64"})
    print("\n■ 方法1: 読み込みをやり直す")
    print(f"dtype         : {good['price'].dtype}")
    print(f"price * 2     : {(good['price'] * 2).iloc[0]}")
    print(f"mean()        : {good['price'].mean():.2f}")

    # 3. 直し方その 2：すでに読み込んだデータを変換する
    by_astype = bad["price"].astype("int64")
    by_to_numeric = pd.to_numeric(bad["price"])
    print("\n■ 方法2: 読み込み済みのデータを変換する")
    print(f"astype('int64')   : {by_astype.dtype} / 1 行目 {by_astype.iloc[0]}")
    print(f"pd.to_numeric()   : {by_to_numeric.dtype} / 1 行目 {by_to_numeric.iloc[0]}")

    # 4. 数値に見えない値が混ざっていると、変換は失敗する
    messy = pd.Series(["1410", "3,200", "", "880"], dtype="str")
    print("\n■ 汚れた値が混ざっている場合（errors='coerce' で欠損にする）")
    print(f"元の値         : {messy.tolist()}")
    print(f"coerce の結果  : {pd.to_numeric(messy, errors='coerce').tolist()}")
    try:
        pd.to_numeric(messy)
        print("errors 指定なし: 変換できてしまいました（想定外です）")
    except ValueError:
        print("errors 指定なし: ValueError（どの値が悪いのか気づける）")


if __name__ == "__main__":
    main()
