"""練習問題3の解答：FakeProvider で POST /api/chat/stream のイベント列を固定する（ネットワークに出ない）。"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator

import httpx2
import pytest

from kondate.verifykit import sse_events

from .app import app, get_provider
from .providers import FakeItem, FakeProvider, ToolCall, Usage, fake_script


@pytest.fixture
def use_fake() -> Iterator[Callable[..., FakeProvider]]:
    def install(*scripts: list[FakeItem]) -> FakeProvider:
        fake = FakeProvider(*scripts)
        app.dependency_overrides[get_provider] = lambda: fake
        return fake

    yield install
    app.dependency_overrides.clear()


async def stream_events(message: str = "鶏むね肉で何を作れる？") -> list[dict]:
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/chat/stream", json={"message": message})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    return sse_events(r.text.split("\n"))


async def test_text_is_relayed_in_contract_order(use_fake: Callable[..., FakeProvider]) -> None:
    use_fake(fake_script("塩炒めがおすすめです。", usage=Usage(12, 11)))
    events = await stream_events()
    assert [e["event"] for e in events] == ["start", "delta", "delta", "usage", "done"]
    assert uuid.UUID(events[0]["data"]["message_id"]).version == 7
    assert [e["data"] for e in events[1:]] == [
        {"text": "塩炒めがおす"}, {"text": "すめです。"},
        {"input_tokens": 12, "output_tokens": 11}, {"stop_reason": "end_turn"}]


async def test_tool_events_are_not_sent_yet(use_fake: Callable[..., FakeProvider]) -> None:
    use_fake(fake_script("探します。", usage=Usage(300, 42),
                         tool_calls=[ToolCall("toolu_fake_1", "search_recipes", {"ingredients": ["鶏むね肉"]})]))
    events = await stream_events()
    assert [e["event"] for e in events] == ["start", "delta", "usage", "done"]
    assert events[-1]["data"] == {"stop_reason": "tool_use"}


async def test_empty_text_still_has_start_usage_done(use_fake: Callable[..., FakeProvider]) -> None:
    fake = use_fake(fake_script("", usage=Usage(5, 1)))
    events = await stream_events("こんにちは")
    assert [e["event"] for e in events] == ["start", "usage", "done"]
    assert [r.messages for r in fake.requests] == [[{"role": "user", "content": "こんにちは"}]]
