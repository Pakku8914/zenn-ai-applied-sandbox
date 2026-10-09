"""後半・練習問題2の解答：SSE が始まる前の失敗（入力の誤り）を、read_sse() で JSON として受け取る。"""

from __future__ import annotations

import pytest

from ..providers import FakeProvider, fake_script
from ..store import MemoryStore
from ..testkit import FAKE_ANSWER, chat_once


@pytest.mark.parametrize("message", ["", "あ" * 2001], ids=["empty", "too_long"])
async def test_invalid_message_is_json_422(message: str, memory_store: MemoryStore) -> None:
    fake = FakeProvider(fake_script(FAKE_ANSWER))
    run = await chat_once(fake, memory_store, message)
    assert run.status == 422
    assert run.headers["content-type"].startswith("application/json")
    err = run.body["error"]
    assert (err["type"], err["message"]) == ("invalid_request", "入力値が正しくありません：message")
    assert err["request_id"] == run.headers["x-request-id"]
    assert (run.events, fake.requests, memory_store.turns) == ([], [], [])  # 上流は呼ばれず、SSE も始まらない
