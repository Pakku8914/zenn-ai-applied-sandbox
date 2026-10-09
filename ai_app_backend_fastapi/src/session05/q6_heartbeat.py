"""練習問題6の解答：元の列が interval 秒黙ったら「: ping」を挟む、自前のハートビート。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TypeVar

import anyio
from fastapi.sse import ServerSentEvent

T = TypeVar("T")


def ping() -> ServerSentEvent:
    return ServerSentEvent(comment="ping")


async def _next(it: AsyncIterator[T]) -> T:
    return await anext(it)


async def with_heartbeat(source: AsyncIterator[T], interval: float) -> AsyncIterator[T | ServerSentEvent]:
    if interval <= 0:
        raise ValueError("interval は正の秒数です")
    it = aiter(source)
    pending: asyncio.Task[T] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(_next(it))  # 次の1個を取りに行く係（ping を送る間も待ち続ける）
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield ping()  # 取りに行く係はそのまま。もう一度 interval だけ待つ
                continue
            task, pending = pending, None
            try:
                item = task.result()
            except StopAsyncIteration:
                return
            yield item
    finally:
        with anyio.CancelScope(shield=True):  # 止められている最中でも、後始末は最後までやる
            if pending is not None:  # 途中で閉じられた：取りに行く係を止め、止まりきるまで待つ
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            aclose = getattr(it, "aclose", None)
            if aclose is not None:
                await aclose()
