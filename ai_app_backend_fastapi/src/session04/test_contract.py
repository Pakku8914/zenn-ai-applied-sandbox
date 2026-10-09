"""契約テスト：同じテストを anthropic・openai・fake の3実装に流す。"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from .contract_kit import (FAKE_GET, FAKE_RATE_LIMITED, FAKE_STREAM_ERROR, FAKE_TEXT, FAKE_TOOL, PROVIDERS,
                           SEARCH_INPUT, TEXT_REQ, TOOL_REQ, TOOL_RESULT, provider_under_test)
from .providers import (Done, ProviderError, TextDelta, ToolCallDelta, ToolCallDone, ToolCallStart, accumulate,
                        assistant_message)

contract = pytest.mark.parametrize("name", PROVIDERS)


@contract
async def test_complete_returns_normalized_text(name: str) -> None:
    async with provider_under_test(name, FAKE_TEXT) as p:
        result = await p.complete(TEXT_REQ)
    assert result.text and result.tool_calls == []
    assert result.stop_reason == "end_turn"
    assert result.usage.input_tokens > 0 and result.usage.output_tokens > 0


@contract
async def test_stream_folds_into_complete(name: str) -> None:
    async with provider_under_test(name, FAKE_TEXT) as p:
        result = await p.complete(TEXT_REQ)
        events = [ev async for ev in p.stream(TEXT_REQ)]
    assert isinstance(events[-1], Done)
    assert sum(isinstance(ev, Done) for ev in events) == 1
    assert accumulate(events) == replace(result, request_id=None)


@contract
async def test_tool_call_events_are_ordered(name: str) -> None:
    async with provider_under_test(name, FAKE_TOOL) as p:
        events = [ev async for ev in p.stream(TOOL_REQ)]
    start = next(i for i, ev in enumerate(events) if isinstance(ev, ToolCallStart))
    done = next(i for i, ev in enumerate(events) if isinstance(ev, ToolCallDone))
    deltas = [ev for ev in events[start + 1:done] if isinstance(ev, ToolCallDelta)]
    assert events[start].name == "search_recipes" and deltas
    assert all(d.id == events[start].id == events[done].id for d in deltas)
    assert json.loads("".join(d.partial_json for d in deltas)) == events[done].input == SEARCH_INPUT
    assert isinstance(events[-1], Done) and events[-1].stop_reason == "tool_use"


@contract
async def test_tool_result_round_trip(name: str) -> None:
    async with provider_under_test(name, FAKE_TOOL, FAKE_GET) as p:
        first = await p.complete(TOOL_REQ)
        tool_result = {"type": "tool_result", "tool_use_id": first.tool_calls[0].id, "content": TOOL_RESULT}
        second = await p.complete(replace(TOOL_REQ, messages=[
            *TOOL_REQ.messages, assistant_message(first), {"role": "user", "content": [tool_result]}]))
    assert [(c.name, c.input) for c in second.tool_calls] == [("get_recipe", {"recipe_id": "R001"})]


@contract
async def test_rate_limit_becomes_provider_error(name: str) -> None:
    async with provider_under_test(name, FAKE_RATE_LIMITED, fault="429") as p:
        with pytest.raises(ProviderError) as info:
            await p.complete(TEXT_REQ)
    assert (info.value.kind, info.value.provider, info.value.retryable) == ("rate_limited", name, True)


@contract
async def test_stream_error_becomes_provider_error(name: str) -> None:
    received = []
    async with provider_under_test(name, FAKE_STREAM_ERROR, fault="sse-error") as p:
        with pytest.raises(ProviderError) as info:
            async for ev in p.stream(TEXT_REQ):
                received.append(ev)
    assert info.value.kind == "stream_error"
    assert received and all(isinstance(ev, TextDelta) for ev in received)
