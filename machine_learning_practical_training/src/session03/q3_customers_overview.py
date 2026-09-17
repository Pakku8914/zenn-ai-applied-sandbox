"""問題3 の解答: customers.csv を型を明示して読み、info で欠損を見つける。

使い方:
    docker compose exec lab python src/session03/q3_customers_overview.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

CUSTOMERS_DTYPE = {
    "customer_id": "str",
    "birth_year": "int64",
    "region": "str",
    "channel": "str",
}


def main() -> None:
    customers = pd.read_csv(
        DATA_DIR / "customers.csv",
        dtype=CUSTOMERS_DTYPE,
        parse_dates=["signup_date"],
    )

    print(f"customers.csv : {customers.shape[0]} 行 × {customers.shape[1]} 列")

    print("\n■ info()")
    customers.info(memory_usage=False)

    print("\n■ 列ごとの欠損数")
    print(customers.isna().sum())

    missing_cols = [c for c in customers.columns if bool(customers[c].isna().any())]
    date_cols = [c for c in customers.columns if str(customers[c].dtype).startswith("datetime64")]

    print(f"\n欠損がある列   : {missing_cols}")
    print(f"region の欠損  : {int(customers['region'].isna().sum())} 件")
    print(f"region の実数  : {int(customers['region'].notna().sum())} 件")
    print(f"日時になった列 : {date_cols} -> {customers['signup_date'].dtype}")


if __name__ == "__main__":
    main()
