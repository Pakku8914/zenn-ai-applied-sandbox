"""チェーン代入が黙って捨てられることを実機で確認する（pandas 3.0）。

警告は隠さない。catch_warnings(record=True) で「どんな警告が出たか」を
つかんで表示し、値が変わっていないことを目で確かめる。

使い方:
    docker compose exec lab python src/session04/chained_assignment.py
"""

from __future__ import annotations

import warnings

from common import load_orders

HEAD = "A value is being set on a copy of a DataFrame or Series through chained assignment."


def main() -> None:
    orders = load_orders()
    df = orders.copy()  # 元のデータは壊さない

    print(f"代入前の quantity        : {df.loc[0, 'quantity']}")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        df["quantity"][0] = 999  # やってはいけない書き方
    print(f"出た警告の種類           : {sorted({w.category.__name__ for w in caught})}")
    print(f"警告文の先頭は想定どおりか: {any(str(w.message).startswith(HEAD) for w in caught)}")
    print(f"代入後の quantity        : {df.loc[0, 'quantity']}（変わっていない）")

    df.loc[0, "quantity"] = 999
    print(f"loc で代入した後         : {df.loc[0, 'quantity']}")

    df.loc[df["customer_id"] == "C00001", "quantity"] = 0
    print(f"条件付きで 0 にした件数  : {(df['quantity'] == 0).sum()} 件")
    print(f"元の orders は無傷か     : {orders.loc[0, 'quantity'] == 1}")


if __name__ == "__main__":
    main()
