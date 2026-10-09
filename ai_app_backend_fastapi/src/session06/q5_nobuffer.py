"""後半の練習問題4：text/event-stream の応答にだけ X-Accel-Buffering: no を足す ASGI ミドルウェア。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class NoBufferingMiddleware:
    """SSE の応答に X-Accel-Buffering: no を付ける。すでに値があれば、エンドポイントの指定を優先する。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if headers.get("content-type", "").startswith("text/event-stream") \
                        and "x-accel-buffering" not in headers:
                    headers["x-accel-buffering"] = "no"
            await send(message)

        await self.app(scope, receive, send_with_header)


app = FastAPI(title="後半の練習問題4")
app.add_middleware(NoBufferingMiddleware)


async def _ticks() -> AsyncIterator[str]:
    for n in range(1, 6):  # 本文の /api/s06/ticks と同じく、0.3 秒おきに5個
        if n > 1:
            await asyncio.sleep(0.3)
        yield f'event: tick\ndata: {{"n": {n}}}\n\n'


@app.get("/ticks")
async def ticks() -> StreamingResponse:
    return StreamingResponse(_ticks(), media_type="text/event-stream")


@app.get("/ticks-buffered")
async def ticks_buffered() -> StreamingResponse:
    # 少しずつ届かなくてよい（ためて送ってよい）とエンドポイントが決めた例
    return StreamingResponse(_ticks(), media_type="text/event-stream", headers={"x-accel-buffering": "yes"})


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
