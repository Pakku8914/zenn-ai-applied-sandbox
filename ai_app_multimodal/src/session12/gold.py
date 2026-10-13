"""正解データ（セッション12）。tools/make_media.py が画像・PDF を描くときに使った元データから作る。

正解を手で書き写さないのは、画像を作り直したときに「正解だけが古いまま」になるのを防ぐため。
絵から決められない値は None にして採点から外す（外したことが正解データに残る）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from kondate.media import EXPECTED_SHA12, media_path
from tools.make_media import FRIDGE_ITEMS, PURCHASED_AT, RECEIPT_ITEMS, STORE

# 冷蔵庫の絵で、図形から数えられる数量。卵は4個描いている（make_fridge の range(4)）。
# キャベツは円1つで描いてあり、丸ごとか半分かは絵から決められないので None（数量は採点しない）
SHAPE_AMOUNT = {"circle": None, "rect": 1, "eggs": 4, "carrot": 1, "carton": 1}


@dataclass(frozen=True)
class Gold:
    media: str                # media/ のファイル名
    items: tuple[dict, ...]   # 1件ずつの {name, …}。値が None の項目は採点しない
    header: dict              # 全体の項目（レシートの店名・購入日・合計）。冷蔵庫は空


def fridge_gold() -> Gold:
    items = tuple({"name": name, "amount": SHAPE_AMOUNT[shape]} for name, _color, shape, _box in FRIDGE_ITEMS)
    return Gold("fridge.jpg", items, {})


def receipt_gold(media: str) -> Gold:
    """レシートの画像（receipt.png）と PDF（receipt.pdf）は同じ中身なので、正解も同じ。"""
    # レシートに個数の記載は無い＝各1個（ReceiptItem の説明「書かれていなければ1」とそろえる）
    items = tuple({"name": name, "quantity": 1, "price": price} for name, price in RECEIPT_ITEMS)
    header = {"store": STORE, "purchased_at": PURCHASED_AT[:10], "total": sum(p for _, p in RECEIPT_ITEMS)}
    return Gold(media, items, header)


def check_media(names: Iterable[str]) -> None:
    """正解データは make_media.py の版と対になっている。画像・PDF が別物なら採点しない。"""
    for name in sorted(names):
        got = hashlib.sha256(media_path(name).read_bytes()).hexdigest()[:12]
        if got != EXPECTED_SHA12[name]:
            raise RuntimeError(f"{name} が正解データと別の版です（SHA256 先頭12桁 {got}）。git で media/ を元に戻してください")
