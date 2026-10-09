"""単体の層：FakeProvider と MemoryStore だけで、アプリの分岐を速く確かめる（mockllm・DB・Redis を使わない）。"""

from __future__ import annotations

import pytest

from ..errors import MESSAGES
from ..providers import FakeProvider, ProviderError, TextDelta, Usage, fake_script
from ..store import MemoryStore
from ..testkit import FAKE_ANSWER, PROMPT, chat_once


async def test_success_streams_and_saves(memory_store: MemoryStore) -> None:
    fake = FakeProvider(fake_script(FAKE_ANSWER, usage=Usage(34, 20)))
    run = await chat_once(fake, memory_store)
    assert run.shape() == "start → delta×4 → usage → done"
    assert run.data_of("usage") == [{"input_tokens": 34, "output_tokens": 20}]
    assert [t.answer for t in memory_store.turns] == [FAKE_ANSWER]
    assert fake.requests[0].messages == [{"role": "user", "content": PROMPT}]  # 上流へ送った要求も確かめられる


@pytest.mark.parametrize(("kind", "status", "type_"), [
    ("rate_limited", 429, "rate_limited"),
    ("overloaded", 503, "upstream_unavailable"),
    ("timeout", 504, "upstream_timeout"),
    ("auth", 502, "upstream_error"),
])
async def test_prestart_failure_is_json(kind: str, status: int, type_: str, memory_store: MemoryStore) -> None:
    retry_after = 3 if kind == "rate_limited" else None
    fake = FakeProvider([ProviderError(kind, provider="fake", retry_after=retry_after)])
    run = await chat_once(fake, memory_store)
    assert (run.status, run.body["error"]["type"]) == (status, type_)
    assert run.body["error"]["message"] == MESSAGES[type_]
    assert run.headers.get("retry-after") == ("3" if status == 429 else None)
    assert (run.events, memory_store.turns) == ([], [])  # SSE は始まらず、何も保存しない


async def test_midstream_failure_is_error_event(memory_store: MemoryStore) -> None:
    fake = FakeProvider([TextDelta("鶏むね肉とキ"), TextDelta("ャベツの塩炒"),
                         ProviderError("stream_error", provider="fake", status_code=200)])
    run = await chat_once(fake, memory_store)
    assert (run.status, run.shape()) == (200, "start → delta×2 → error")
    err = run.data_of("error")[0]
    assert (err["type"], err["message"]) == ("upstream_error", MESSAGES["upstream_error"])
    assert err["request_id"] == run.headers["x-request-id"]
    assert memory_store.turns == []
