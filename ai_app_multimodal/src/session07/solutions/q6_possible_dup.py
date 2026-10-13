"""問題6：撮り直した写真や、同じレシートの PDF のように「SHA256 は違うが中身が同じ」取り込みに印を付ける。

SHA256 は1バイトでも違えば別物になるので、receipt.png と receipt.pdf（同じ買い物）は両方とも取り込めてしまう。
読み取った中身（店名・購入日・合計）が既存のレシートと同じなら possible_duplicate の印を付けて人に回す。
本当に同じ日に同じ店で同じ額を2回買うこともありうるので、409 で断らず、needs_review にとどめる。

    docker compose exec api python -m src.session07.solutions.q6_possible_dup
"""

from __future__ import annotations

from src.session07.app import ReceiptStore, StoredReceipt
from src.session07.models import ReceiptRead
from src.session07.pdftext import squash

MSG_POSSIBLE_DUPLICATE = "同じ店・同じ日・同じ合計のレシートがすでに取り込まれています。二重に取り込んでいないか確かめてください"


def content_key(read: ReceiptRead) -> tuple[str, str, int]:
    return squash(read.store), read.purchased_at, read.total  # 店名は空白・全角半角の違いを吸収して比べる


def possible_duplicate(store: ReceiptStore, user_id: str, read: ReceiptRead) -> list[dict]:
    key = content_key(read)
    if any(content_key(r.read) == key for r in store.of_user(user_id)):
        return [{"index": None, "name": None, "reason": "possible_duplicate", "message": MSG_POSSIBLE_DUPLICATE}]
    return []


GOOD = {
    "store": "こんだてマート", "purchased_at": "2026-10-01", "total": 1072,
    "items": [{"name": "鶏むね肉", "quantity": 1, "price": 398}, {"name": "キャベツ", "quantity": 1, "price": 198},
              {"name": "卵（10個入り）", "quantity": 1, "price": 248}, {"name": "牛乳", "quantity": 1, "price": 228}],
}


def run_cases() -> list[tuple[str, list[str]]]:
    store = ReceiptStore()
    first = ReceiptRead.model_validate(GOOD)
    store.add(StoredReceipt("rcp_png", "u001", "sha-png", "image", first, []))
    cases = [
        ("同じレシートの PDF", "u001", GOOD),
        ("店名に空白が入った", "u001", {**GOOD, "store": "こんだて マート"}),
        ("別の日", "u001", {**GOOD, "purchased_at": "2026-09-30"}),
        ("別の利用者", "u002", GOOD),
    ]
    return [(label, [i["reason"] for i in possible_duplicate(store, user, ReceiptRead.model_validate(d))])
            for label, user, d in cases]


if __name__ == "__main__":
    for label, reasons in run_cases():
        print(label, reasons)
    # 同じレシートの PDF ['possible_duplicate']
    # 店名に空白が入った ['possible_duplicate']
    # 別の日 []
    # 別の利用者 []
