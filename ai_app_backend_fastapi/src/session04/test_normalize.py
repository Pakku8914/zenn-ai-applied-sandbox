"""練習問題2の解答：OpenAI の usage と finish_reason を Anthropic の値にそろえる関数のテスト。"""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from .providers import Usage, stop_from_openai, usage_from_openai


def test_cached_tokens_are_moved_out_of_input() -> None:
    u = NS(prompt_tokens=2414, completion_tokens=50, prompt_tokens_details=NS(cached_tokens=2404))
    assert usage_from_openai(u) == Usage(input_tokens=10, output_tokens=50, cache_read_input_tokens=2404)


def test_missing_details_mean_no_cache() -> None:
    u = NS(prompt_tokens=34, completion_tokens=181, prompt_tokens_details=None)
    assert usage_from_openai(u) == Usage(34, 181)


def test_missing_usage_is_zero() -> None:
    assert usage_from_openai(None) == Usage(0, 0)


@pytest.mark.parametrize(("finish", "stop"), [
    ("stop", "end_turn"), ("tool_calls", "tool_use"), ("length", "max_tokens"),
    ("content_filter", "refusal"), (None, "end_turn"),
])
def test_finish_reason_maps_to_anthropic_values(finish: str | None, stop: str) -> None:
    assert stop_from_openai(finish) == stop
