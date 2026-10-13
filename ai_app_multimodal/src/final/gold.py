"""正解データ（セッション12の gold.py の写し）。tools/make_media.py が画像・PDF を描くときに使った元データから作る。"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from kondate.media import EXPECTED_SHA12, media_path
from tools.make_media import FRIDGE_ITEMS, PURCHASED_AT, RECEIPT_ITEMS, STORE

SHAPE_AMOUNT = {"circle": None, "rect": 1, "eggs": 4, "carrot": 1, "carton": 1}


@dataclass(frozen=True)
class Gold:
    media: str
    items: tuple[dict, ...]
    header: dict


def fridge_gold() -> Gold:
    items = tuple({"name": name, "amount": SHAPE_AMOUNT[shape]} for name, _color, shape, _box in FRIDGE_ITEMS)
    return Gold("fridge.jpg", items, {})


def receipt_gold(media: str) -> Gold:
    items = tuple({"name": name, "quantity": 1, "price": price} for name, price in RECEIPT_ITEMS)
    header = {"store": STORE, "purchased_at": PURCHASED_AT[:10], "total": sum(p for _, p in RECEIPT_ITEMS)}
    return Gold(media, items, header)


def check_media(names: Iterable[str]) -> None:
    for name in sorted(names):
        got = hashlib.sha256(media_path(name).read_bytes()).hexdigest()[:12]
        if got != EXPECTED_SHA12[name]:
            raise RuntimeError(f"{name} が正解データと別の版です（SHA256 先頭12桁 {got}）。git で media/ を元に戻してください")
