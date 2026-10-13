"""問題2：整合性検査が、どの読み違いにどの印を付けるかを確かめる。

    docker compose exec api python -m src.session07.solutions.q2_checks
"""

from __future__ import annotations

import copy
from datetime import date

from src.session07.checks import check_receipt
from src.session07.models import ReceiptRead

TODAY = date(2026, 10, 2)
BASE = {
    "store": "こんだてマート",
    "purchased_at": "2026-10-01",
    "items": [
        {"name": "鶏むね肉", "quantity": 1, "price": 398},
        {"name": "キャベツ", "quantity": 1, "price": 198},
        {"name": "卵（10個入り）", "quantity": 1, "price": 248},
        {"name": "牛乳", "quantity": 1, "price": 228},
    ],
    "total": 1072,
}


def receipt(**over) -> ReceiptRead:
    d = copy.deepcopy(BASE)
    extra = over.pop("extra_items", [])
    d["items"] += extra
    d.update(over)
    return ReceiptRead.model_validate(d)


CASES = [
    ("A そのまま", receipt()),
    ("B 合計の桁を入れ替えた", receipt(total=1027)),
    ("C 区切りの無い日付", receipt(purchased_at="20261001")),
    ("D 時刻つきの日付", receipt(purchased_at="2026-10-01 18:42")),
    ("E 値引きの行", receipt(extra_items=[{"name": "値引き", "quantity": 1, "price": -50}], total=1022)),
    ("F 未来の日付と桁違いの合計", receipt(purchased_at="2026-10-31", total=107200)),
]


def results() -> list[tuple[str, list[tuple[str, int | None]]]]:
    return [(label, [(i["reason"], i["index"]) for i in check_receipt(r, TODAY)]) for label, r in CASES]


if __name__ == "__main__":
    for label, found in results():
        print(label, found)
    # A そのまま []
    # B 合計の桁を入れ替えた [('total_mismatch', None)]
    # C 区切りの無い日付 [('invalid_date', None)]
    # D 時刻つきの日付 [('invalid_date', None)]
    # E 値引きの行 [('price_out_of_range', 4)]
    # F 未来の日付と桁違いの合計 [('invalid_date', None), ('total_mismatch', None)]
