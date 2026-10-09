"""練習問題6：猶予つきの先読み。猶予内に最初のイベントが来なければ、先に 200 と start を返す。

- 猶予内に失敗（429・529 など。上流はすぐ断る）→ これまでどおり JSON のエラー本文
- 猶予内に最初の差分 → 本文の prime() と同じ
- 猶予を過ぎた → start を先に送り、あとから来た失敗は error イベントで伝える
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from uuid_utils import uuid7

from .app import ChatIn, build_chat, get_provider
from .errors import install_error_handlers
from .providers import ChatRequest, LLMProvider, ProviderError, StreamEvent
from .relay import Primed, StreamOutcome, estimate_input_tokens, relay_chat

GRACE_SECONDS = 0.3


async def _first(upstream: AsyncIterator[StreamEvent], provider: str) -> StreamEvent:
    try:
        return await anext(upstream)
    except StopAsyncIteration:
        raise ProviderError("bad_response", provider=provider) from None


class Deferred:
    """猶予を過ぎても最初のイベントが届いていない上流。最初の __anext__ で、先読みの続きを待つ。"""

    def __init__(self, task: asyncio.Task[StreamEvent], upstream: AsyncIterator[StreamEvent]) -> None:
        self._task: asyncio.Task[StreamEvent] | None = task
        self._upstream = upstream

    def __aiter__(self) -> Deferred:
        return self

    async def __anext__(self) -> StreamEvent:
        if self._task is not None:
            task, self._task = self._task, None
            return await task  # 失敗なら ProviderError がここで上がる（relay_chat が error イベントにする）
        return await anext(self._upstream)

    async def aclose(self) -> None:
        # 一度も読まれずに閉じられても、裏で走っている先読みを止め、上流を閉じる
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        await self._upstream.aclose()


async def prime_with_grace(provider: LLMProvider, chat: ChatRequest, grace: float = GRACE_SECONDS) -> Primed:
    started = time.perf_counter()
    upstream = provider.stream(chat)
    task = asyncio.create_task(_first(upstream, provider.name))
    done, _ = await asyncio.wait({task}, timeout=grace)
    if done:
        return Primed(chat, upstream, task.result(), started)  # 失敗していればここで ProviderError → JSON
    return Primed(chat, Deferred(task, upstream), None, started)


async def primed_with_grace(body: ChatIn, provider: Annotated[LLMProvider, Depends(get_provider)]) -> Primed:
    return await prime_with_grace(provider, build_chat(body))


app = FastAPI(title="猶予つき先読み（練習問題6）")
app.state.outcomes = deque(maxlen=20)
install_error_handlers(app)


@app.post("/api/chat/stream", response_class=EventSourceResponse)
async def chat_stream(request: Request,
                      primed: Annotated[Primed, Depends(primed_with_grace)]) -> AsyncIterator[ServerSentEvent]:
    outcome = StreamOutcome(request_id=request.state.request_id, message_id=str(uuid7()),
                            input_estimate=estimate_input_tokens(primed.chat))
    events = relay_chat(request, primed, outcome, on_close=request.app.state.outcomes.append)
    async with aclosing(events):
        async for ev in events:
            yield ev
