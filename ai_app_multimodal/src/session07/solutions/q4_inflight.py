"""問題4：同じレシートが同時に2回送られても、LLM を1回しか呼ばないようにする（読み取り中の予約）。

本文の app.py は「読み取る前に find → 読み取ったあとに add」で二重登録は防げるが、
同時に届いた2つのリクエストは両方とも LLM を呼んでしまう（料金が2回分かかる）。
読み取りを始める前に (利用者, SHA256) を「読み取り中」として予約し、後から来た方をすぐ 409 にする。

    docker compose exec api python -m src.session07.solutions.q4_inflight
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable

import anyio
from ulid import ULID

from kondate.llm import ChatRequest, ChatResult, Usage
from kondate.media import media_path
from src.session07.app import ReceiptStore, StoredReceipt
from src.session07.read import InvalidOutput, ReadResult, read_receipt


class ReservingStore(ReceiptStore):
    def __init__(self) -> None:
        super().__init__()
        self._pending: set[tuple[str, str]] = set()  # 読み取り中の (利用者, SHA256)

    def reserve(self, user_id: str, sha256: str) -> bool:
        """取り込み済みでも読み取り中でもなければ予約して True。await を挟まないので2人同時には通らない。"""
        key = (user_id, sha256)
        if key in self._pending or self.find(user_id, sha256) is not None:
            return False
        self._pending.add(key)
        return True

    def release(self, user_id: str, sha256: str) -> None:
        self._pending.discard((user_id, sha256))


async def import_once(store: ReservingStore, user_id: str, raw: bytes,
                      read: Callable[[], Awaitable[ReadResult]]) -> int:
    """取り込みの流れから、二重取り込みに関わる所だけを取り出したもの。HTTP の status を返す。"""
    sha256 = hashlib.sha256(raw).hexdigest()
    if not store.reserve(user_id, sha256):
        return 409
    try:
        result = await read()
        store.add(StoredReceipt(f"rcp_{ULID()}", user_id, sha256, "image", result.receipt, []))
        return 201
    except InvalidOutput:
        return 502
    finally:
        store.release(user_id, sha256)  # 成功なら add のあと、失敗なら何も残さず予約だけ外す


class SlowFake:
    """応答の前に少し待つ FakeProvider。待っている間に2つ目のリクエストが届く状況を作る。"""

    name = "slow-fake"

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.calls = 0

    async def complete(self, req: ChatRequest) -> ChatResult:
        self.calls += 1
        await anyio.sleep(0.05)
        return ChatResult(self._texts.pop(0), [], "end_turn", Usage(778, 104))


GOOD = json.dumps({
    "store": "こんだてマート", "purchased_at": "2026-10-01", "total": 1072,
    "items": [{"name": "鶏むね肉", "quantity": 1, "price": 398}, {"name": "キャベツ", "quantity": 1, "price": 198},
              {"name": "卵（10個入り）", "quantity": 1, "price": 248}, {"name": "牛乳", "quantity": 1, "price": 228}],
}, ensure_ascii=False)
BROKEN = '{"store": "こんだて'


async def run_cases() -> dict:
    raw = media_path("receipt.png").read_bytes()  # 読み取りは偽物なので、バイト列は SHA256 を作るためだけに使う

    store, llm = ReservingStore(), SlowFake([GOOD])
    same = await asyncio.gather(*(import_once(store, "u001", raw, lambda: read_receipt(llm, "image", raw)) for _ in range(2)))
    concurrent = (list(same), llm.calls)

    store, llm = ReservingStore(), SlowFake([BROKEN, BROKEN, GOOD])
    first = await import_once(store, "u001", raw, lambda: read_receipt(llm, "image", raw))
    second = await import_once(store, "u001", raw, lambda: read_receipt(llm, "image", raw))
    return {"concurrent": concurrent, "after_failure": [first, second]}


if __name__ == "__main__":
    print(asyncio.run(run_cases()))
    # {'concurrent': ([201, 409], 1), 'after_failure': [502, 201]}
