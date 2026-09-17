"""型が想定と違うときに起きる不具合を再現し、直す。

使い方:
    docker compose exec lab python src/session03/broken_types.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def main() -> None:
    # 1. price を文字列として読んでしまった場合（読み込み設定のうっかりミスを再現する）
    bad = pd.read_csv(DATA_DIR / "books.csv", dtype={"price": "str"})
    print("■ price を文字列として読むと何が起きるか")
    print(f"price の dtype     : {bad['price'].dtype}")
    print(f"1 行目の price     : {bad['price'].iloc[0]!r}")
    print(f"price * 2 の 1 行目: {(bad['price'] * 2).iloc[0]!r}")
    try:
        bad["price"].mean()
        print("mean() が計算できてしまいました（想定外です）")
    except TypeError as error:
        print(f"mean() を呼ぶと    : {type(error).__name__}")

    # 2. 文字列のままだと「大小の比べ方」まで変わる
    sample = pd.Series(["990", "1000", "540"], dtype="str")
    print("\n■ 文字列の並び順と数値の並び順")
    print(f"文字列のまま並べる : {sample.sort_values().tolist()}")
    print(f"数値に直して並べる : {pd.to_numeric(sample).sort_values().tolist()}")

    # 3. 直し方（読み込み直せるならそれが最善。手元で直すなら astype / to_numeric）
    fixed = bad["price"].astype("int64")
    print("\n■ 直したあと")
    print(f"dtype              : {fixed.dtype}")
    print(f"price * 2 の 1 行目: {(fixed * 2).iloc[0]}")

    # 4. 日時を文字列のまま扱うと .dt が使えない
    orders_raw = pd.read_csv(DATA_DIR / "orders.csv")
    print("\n■ 日時を文字列のまま扱うと")
    print(f"ordered_at の dtype: {orders_raw['ordered_at'].dtype}")
    try:
        orders_raw["ordered_at"].dt.year
        print(".dt が使えてしまいました（想定外です）")
    except AttributeError as error:
        print(f".dt.year を呼ぶと  : {type(error).__name__}")

    repaired = pd.to_datetime(orders_raw["ordered_at"])
    print(f"to_datetime 後に .dt が使えるか: {repaired.dt.year.between(2024, 2026).all()}")


if __name__ == "__main__":
    main()
