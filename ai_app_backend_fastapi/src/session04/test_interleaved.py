"""練習問題5の解答：OpenAI 互換のツール差分が交互に届いても、index で正しく束ねられることのテスト。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from types import SimpleNamespace as NS

import pytest

from .providers import Done, ProviderError, ToolCallDelta, ToolCallDone, ToolCallStart, Usage, normalize_openai_stream


def chunk(*, content: str | None = None, tool_calls: list | None = None, finish: str | None = None,
          usage: NS | None = None) -> NS:
    choices = [] if usage else [NS(delta=NS(content=content, tool_calls=tool_calls), finish_reason=finish)]
    return NS(choices=choices, usage=usage)


def tc(index: int, *, id: str | None = None, name: str | None = None, args: str | None = None) -> NS:
    return NS(index=index, id=id, function=NS(name=name, arguments=args))


async def feed(items: Iterable[NS]) -> AsyncIterator[NS]:
    for item in items:
        yield item


INTERLEAVED = [
    chunk(tool_calls=[tc(0, id="call_a", name="search_recipes", args="")]),
    chunk(tool_calls=[tc(1, id="call_b", name="get_recipe", args="")]),
    chunk(tool_calls=[tc(0, args='{"ingredients": ')]),
    chunk(tool_calls=[tc(1, args='{"recipe_id": "R001"}')]),
    chunk(tool_calls=[tc(0, args='["卵"]}')]),
    chunk(finish="tool_calls"),
    chunk(usage=NS(prompt_tokens=50, completion_tokens=30, prompt_tokens_details=None)),
]


async def test_interleaved_tool_calls_are_grouped_by_index() -> None:
    events = [ev async for ev in normalize_openai_stream(feed(INTERLEAVED))]
    assert events == [
        ToolCallStart("call_a", "search_recipes"),
        ToolCallStart("call_b", "get_recipe"),
        ToolCallDelta("call_a", '{"ingredients": '),
        ToolCallDelta("call_b", '{"recipe_id": "R001"}'),
        ToolCallDelta("call_a", '["卵"]}'),
        ToolCallDone("call_a", "search_recipes", {"ingredients": ["卵"]}),
        ToolCallDone("call_b", "get_recipe", {"recipe_id": "R001"}),
        Done("tool_use", Usage(50, 30)),
    ]


async def test_stream_without_finish_reason_is_an_error() -> None:
    with pytest.raises(ProviderError) as info:
        [ev async for ev in normalize_openai_stream(feed(INTERLEAVED[:5]))]
    assert info.value.kind == "connection"


async def test_broken_arguments_are_bad_response() -> None:
    broken = [chunk(tool_calls=[tc(0, id="call_a", name="get_recipe", args='{"recipe_id": ')]),
              chunk(finish="tool_calls")]
    with pytest.raises(ProviderError) as info:
        [ev async for ev in normalize_openai_stream(feed(broken))]
    assert info.value.kind == "bad_response"
