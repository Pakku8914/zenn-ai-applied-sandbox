"""SSE をストリームとして読むテスト：ヘッダ・1行の JSON・終端イベントの位置・保存した ID との対応。"""

from __future__ import annotations

import json

import pytest

from ..providers import FakeProvider, ProviderError, TextDelta, Usage, fake_script
from ..store import MemoryStore
from ..testkit import FAKE_ANSWER, chat_once


async def test_headers_and_framing(memory_store: MemoryStore) -> None:
    run = await chat_once(FakeProvider(fake_script(FAKE_ANSWER, usage=Usage(34, 20))), memory_store)
    assert run.headers["content-type"].startswith("text/event-stream")
    assert (run.headers["cache-control"], run.headers["x-accel-buffering"]) == ("no-cache", "no")
    assert len(run.data_lines) == len(run.events)  # 1イベントに data: 行は1つ（JSON に改行が無い）
    assert all(isinstance(json.loads(line), dict) for line in run.data_lines)
    assert "鶏むね肉" in run.data_lines[1]  # 日本語がエスケープされずに届く


@pytest.mark.parametrize(("script", "terminal"), [
    (fake_script(FAKE_ANSWER, usage=Usage(34, 20)), "done"),
    ([TextDelta("鶏むね肉とキ"), ProviderError("overloaded", provider="fake", status_code=529)], "error"),
], ids=["done", "error"])
async def test_exactly_one_terminal_event_at_end(script: list, terminal: str, memory_store: MemoryStore) -> None:
    run = await chat_once(FakeProvider(script), memory_store, stop_at_terminal=False)  # 最後まで読む
    names = run.names()
    assert names[0] == "start"
    assert names[-1] == terminal
    assert sum(n in ("done", "error") for n in names) == 1


async def test_start_message_id_is_the_saved_id(memory_store: MemoryStore) -> None:
    run = await chat_once(FakeProvider(fake_script(FAKE_ANSWER, usage=Usage(34, 20))), memory_store)
    saved = memory_store.turns[0]
    assert run.data_of("start")[0]["message_id"] == saved.message_id
    assert saved.request_id == run.headers["x-request-id"]
