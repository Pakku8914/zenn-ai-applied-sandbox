"""中間プロジェクト1のテスト：同じテストを FakeProvider と mockllm の両方に流す。

    docker compose exec api python -m pytest src/mid01/test_mid01.py

Fake は台本で決まった失敗を起こせる（速く、上流が要らない）。mockllm は本物の SDK と SSE の解析を通る。
両方で同じ結果になることが、「差し替え層の上で組み立てた」ことの確認になる。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from kondate.db import engine

from .app import app
from .harness import (PROMPT, alembic, alternates, asgi_client, data_of, expected_shape, fake_tool_search,
                      fixture_texts, mock_llm, new_conversation, post_message, reset_mock, rows_of, shape, stored,
                      wired)
from .loop import STEP_LIMIT, ToolLimits
from .providers import FakeProvider, LLMProvider, ProviderError, TextDelta, ToolCall, fake_script
from .tokens import ApproxTokenCounter, TokenCounter
from .turn import STEP_LIMIT_NOTE

BOTH = pytest.mark.parametrize("name", ["fake", "mockllm"])
USER = ("user", "complete", None)


@pytest.fixture(scope="module", autouse=True)
def migrated() -> None:
    alembic("upgrade", "head")  # 何度実行しても同じ（すでに head なら何もしない）


@pytest.fixture(autouse=True)
async def cleanup() -> AsyncIterator[None]:
    yield
    app.dependency_overrides.clear()
    await engine.dispose()  # テストごとにイベントループが変わるので、接続をプールに持ち越さない


@asynccontextmanager
async def upstream(name: str, fake: FakeProvider,
                   fault: str | None = None) -> AsyncIterator[tuple[LLMProvider, TokenCounter]]:
    """name が fake なら台本の Fake、mockllm なら障害注入ヘッダ付きの本物の SDK を返す。"""
    if name == "fake":
        yield fake, ApproxTokenCounter()
        return
    await reset_mock()
    async with mock_llm({"x-mock-fault": fault} if fault else None) as pair:
        yield pair


async def one_turn(provider: LLMProvider, counter: TokenCounter, content: str = PROMPT, **options):
    with wired(app, provider, counter=counter, **options):
        async with asgi_client(app) as c:
            cid = await new_conversation(c)
            r, events = await post_message(c, cid, content)
            return r, events, await stored(c, cid)


@BOTH
async def test_turn_is_saved_with_tool_pairs(name: str) -> None:
    async with upstream(name, fake_tool_search()) as (provider, counter):
        r, events, saved = await one_turn(provider, counter)
    assert r.status_code == 200
    assert shape(events) == expected_shape()
    assert rows_of(saved) == [USER, ("assistant", "complete", "tool_use"), USER,
                              ("assistant", "complete", "tool_use"), USER, ("assistant", "complete", "end_turn")]
    assert saved[-1]["id"] == events[0]["data"]["message_id"]
    assert saved[-1]["content"] == [{"type": "text", "text": fixture_texts()[2]}]


async def test_tool_error_is_saved_as_tool_result() -> None:
    fake = FakeProvider(
        fake_script("確認しますね。", tool_calls=[ToolCall("toolu_t1", "get_recipe", {"recipe_id": "R999"})]),
        fake_script("R999 は見つかりませんでした。"))
    r, events, saved = await one_turn(fake, ApproxTokenCounter(), "R999 の作り方は？")
    assert [x["is_error"] for x in data_of(events, "tool_result")] == [True]
    assert saved[2]["content"][0]["is_error"] is True
    assert {m["status"] for m in saved} == {"complete"}


async def test_max_steps_closes_turn_with_assistant() -> None:
    fake = FakeProvider(fake_script("もう一度探します。",
                                    tool_calls=[ToolCall("toolu_t2", "search_recipes", {"ingredients": ["卵"]})]))
    r, events, saved = await one_turn(fake, ApproxTokenCounter(), "卵のレシピを探して",
                                      limits=ToolLimits(max_steps=2))
    assert data_of(events, "done") == [{"stop_reason": "max_steps"}]
    assert data_of(events, "tool_result")[-1]["output"] == STEP_LIMIT
    assert saved[-1]["content"] == [{"type": "text", "text": STEP_LIMIT_NOTE}]
    assert (saved[-1]["role"], saved[-1]["stop_reason"]) == ("assistant", "max_steps")
    assert alternates(saved)  # tool_result だけの user で往復を終えていない


@BOTH
async def test_prestart_429_saves_nothing(name: str) -> None:
    fake = FakeProvider([ProviderError("rate_limited", provider="fake", retry_after=1)])
    async with upstream(name, fake, fault="429") as (provider, counter):
        r, events, saved = await one_turn(provider, counter)
    assert (r.status_code, r.json()["error"]["type"], r.headers["retry-after"]) == (429, "rate_limited", "1")
    assert (events, saved) == ([], [])


@BOTH
async def test_midstream_error_saves_partial(name: str) -> None:
    head = fixture_texts()[0]
    fake = FakeProvider([TextDelta(head[:6]), TextDelta(head[6:12]), ProviderError("stream_error", provider="fake")])
    async with upstream(name, fake, fault="sse-error") as (provider, counter):
        r, events, saved = await one_turn(provider, counter)
    assert shape(events) == "start → delta×2 → error"
    assert data_of(events, "error")[0]["type"] == "upstream_error"
    assert rows_of(saved) == [USER, ("assistant", "partial", None)]
    assert saved[1]["content"] == [{"type": "text", "text": head[:12]}]
