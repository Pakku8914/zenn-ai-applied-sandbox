"""録画再生：mockllm から録ったカセットを再生し、mockllm なしで決定的に回す。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ..app import ChatIn, build_chat
from ..cassette import CassetteMismatch, ReplayProvider, event_from_json, event_to_json
from ..providers import Done, ProviderError, TextDelta, ToolCallDelta, ToolCallDone, ToolCallStart, Usage
from ..store import MemoryStore
from ..testkit import chat_once

CASSETTES = Path(__file__).resolve().parent / "cassettes"  # python -m src.session15.record で作る


def replay(name: str) -> ReplayProvider:
    return ReplayProvider.load(CASSETTES / f"{name}.jsonl")


async def test_replay_success(memory_store: MemoryStore) -> None:
    provider = replay("chat_ok")
    run = await chat_once(provider, memory_store)
    assert run.shape() == "start → delta×32 → usage → done"
    assert run.data_of("usage") == [{"input_tokens": 34, "output_tokens": 181}]
    assert len(memory_store.turns[0].answer) == 192
    provider.assert_all_used()


async def test_replay_midstream_error(memory_store: MemoryStore) -> None:
    provider = replay("chat_sse_error")
    run = await chat_once(provider, memory_store)
    assert run.shape() == "start → delta×2 → error"
    assert run.data_of("error")[0]["type"] == "upstream_error"
    assert memory_store.turns == []
    provider.assert_all_used()


async def test_mismatch_fails_loudly() -> None:
    provider = replay("chat_ok")
    other = build_chat(ChatIn(message="卵とトマトで何か作れる？"))
    with pytest.raises(CassetteMismatch, match="messages"):
        await anext(provider.stream(other))


def test_unused_entries_are_reported() -> None:
    with pytest.raises(CassetteMismatch, match="0 件しか"):
        replay("chat_ok").assert_all_used()


def test_events_roundtrip() -> None:
    items = [TextDelta("鶏むね肉"), ToolCallStart("toolu_1", "get_recipe"), ToolCallDelta("toolu_1", '{"recipe_id"'),
             ToolCallDone("toolu_1", "get_recipe", {"recipe_id": "R001"}), Done("tool_use", Usage(10, 5, 2, 1))]
    assert [event_from_json(json.loads(json.dumps(event_to_json(x)))) for x in items] == items
    err = event_from_json(event_to_json(ProviderError("rate_limited", provider="anthropic", status_code=429,
                                                      request_id="req_mock_000001", retry_after=1)))
    assert isinstance(err, ProviderError)
    assert (err.kind, err.provider, err.status_code, err.retry_after, err.request_id) == \
        ("rate_limited", "anthropic", 429, 1, None)  # 上流の request-id は録らない
