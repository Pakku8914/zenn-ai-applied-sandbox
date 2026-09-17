"""日時型への変換と、タイムゾーンの扱いを確かめる。

使い方:
    docker compose exec lab python src/session07/parse_and_tz.py
"""

from __future__ import annotations

import pandas as pd

from common import REFERENCE_DATE, load_orders


def main() -> None:
    orders = load_orders()
    ordered_at = orders["ordered_at"]

    # 1. parse_dates で読み込んだ列は datetime64[us]（pandas 3.0 の既定の精度）
    first, last = ordered_at.min(), ordered_at.max()
    print(f"ordered_at の dtype : {ordered_at.dtype}")
    print(f"最初の注文          : {first:%Y-%m-%d}")
    print(f"最後の注文          : {last:%Y-%m-%d}")
    print(f"期間の長さ          : {(last - first).days + 1} 日")

    # 2. 壊れた値が混ざっている場合。errors="coerce" は変換できない値を NaT にする
    raw = pd.Series(["2026-09-01", "2026-09-31", "不明", ""])
    coerced = pd.to_datetime(raw, errors="coerce")
    print(f"\n変換できた件数      : {int(coerced.notna().sum())} 件")
    print(f"NaT になった件数    : {int(coerced.isna().sum())} 件")

    # 3. タイムゾーン。読み込んだ日時は「どこの時刻か」の情報を持たない（naive）
    jst = REFERENCE_DATE.tz_localize("Asia/Tokyo")
    print(f"\n基準日（naive）     : {REFERENCE_DATE}")
    print(f"日本時間として付与  : {jst}")
    print(f"UTC に変換          : {jst.tz_convert('UTC')}")
    print(f"UTC 換算の日付      : {jst.tz_convert('UTC').date()}")


if __name__ == "__main__":
    main()
