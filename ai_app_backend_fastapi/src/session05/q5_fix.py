"""練習問題5の解答：切断しても上流が止まらない中継（bad）と、直したもの（good）。

どちらも「上流を読む係」をバックグラウンドのタスクに分け、キューで受け渡す形にしている。
（ハートビートやツールの実行と並べて動かしたくなると、この形を選びたくなる）
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Annotated

import anyio
from fastapi import Depends, FastAPI, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from uuid_utils import uuid7

from .app import ChatIn
from .providers import ChatRequest, Done, LLMProvider, StreamEvent, TextDelta
from .sse import delta_event, done_event, start_event, usage_event

app = FastAPI(title="練習問題5")
_background: set[asyncio.Task] = set()  # タスクが途中で回収されないよう参照を持つ（asyncio の作法どおり）


def get_provider(request: Request) -> LLMProvider:
    return request.app.state.provider


def chat_of(body: ChatIn) -> ChatRequest:
    return ChatRequest(messages=[{"role": "user", "content": body.message}])


async def pump(provider: LLMProvider, chat: ChatRequest, queue: asyncio.Queue[StreamEvent | None]) -> None:
    # queue.put() で止められても上流のジェネレータが置き去りにならないよう、aclosing で包む
    async with aclosing(provider.stream(chat)) as upstream:
        async for ev in upstream:
            await queue.put(ev)
    await queue.put(None)  # 終わりの印


def to_sse(ev: StreamEvent) -> list[ServerSentEvent]:
    if isinstance(ev, TextDelta):
        return [delta_event(ev.text)]
    if isinstance(ev, Done):
        return [usage_event(ev.usage), done_event(ev.stop_reason)]
    return []


@app.post("/q5/bad", response_class=EventSourceResponse)
async def bad(body: ChatIn, provider: Annotated[LLMProvider, Depends(get_provider)]) -> AsyncIterator[ServerSentEvent]:
    queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
    task = asyncio.create_task(pump(provider, chat_of(body), queue))
    _background.add(task)
    task.add_done_callback(_background.discard)
    yield start_event(str(uuid7()))
    while (ev := await queue.get()) is not None:
        for out in to_sse(ev):
            yield out
    # クライアントが途中で去っても、task は誰にも止められず、最後まで上流を読む


@app.post("/q5/good", response_class=EventSourceResponse)
async def good(body: ChatIn, request: Request,
               provider: Annotated[LLMProvider, Depends(get_provider)]) -> AsyncIterator[ServerSentEvent]:
    queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue(maxsize=16)  # 上流が先走りしすぎないよう上限を付ける
    task = asyncio.create_task(pump(provider, chat_of(body), queue))
    try:
        yield start_event(str(uuid7()))
        while (ev := await queue.get()) is not None:
            if await request.is_disconnected():
                break
            for out in to_sse(ev):
                yield out
        await task  # 正常に終わったときは、pump の例外もここで受け取る
    finally:
        if not task.done():
            task.cancel()  # 上流を読む係を止める → provider.stream() が閉じ、上流への接続も閉じる
        with anyio.CancelScope(shield=True):
            await asyncio.gather(task, return_exceptions=True)  # 止まりきるまで待つ
