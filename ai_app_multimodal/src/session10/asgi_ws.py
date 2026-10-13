"""ASGI アプリに、WebSocket で直接つなぐ小さな道具（ネットワークを通さない）。

httpx2 の ASGITransport は HTTP しか扱えず、WebSocket を試せない。そこで ASGI の取り決め
（websocket.connect／receive／send／close のメッセージ）を自分で受け渡す。
verify と計測で使う。api コンテナの APP_MODULE を切り替えなくてよい。
"""

from __future__ import annotations

import asyncio
from typing import Any


class AsgiWebSocket:
    def __init__(self, app: Any, path: str = "/ws/voice", headers: dict[str, str] | None = None) -> None:
        self._app = app
        extra = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
        self._scope = {
            "type": "websocket", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1",
            "scheme": "ws", "server": ("test", 80), "client": ("127.0.0.1", 50000),
            "root_path": "", "path": path, "raw_path": path.encode(), "query_string": b"",
            "headers": [(b"host", b"test"), *extra], "subprotocols": [], "state": {},
        }
        self._to_app: asyncio.Queue[dict] = asyncio.Queue()
        self._from_app: asyncio.Queue[dict] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self.accepted = False
        self.close_code: int | None = None

    async def __aenter__(self) -> AsgiWebSocket:
        self._to_app.put_nowait({"type": "websocket.connect"})
        self._task = asyncio.create_task(self._app(self._scope, self._to_app.get, self._from_app.put))
        first = await self._next()
        if first is not None and first["type"] == "websocket.accept":
            self.accepted = True
        elif first is not None and first["type"] == "websocket.close":
            self.close_code = first.get("code", 1000)     # accept の前に閉じられた＝接続を断られた
        return self

    async def __aexit__(self, *exc: object) -> None:
        if not self._task.done():
            self._to_app.put_nowait({"type": "websocket.disconnect", "code": 1000})
        await self._task                                  # アプリの中で起きた例外は、ここで表に出る

    async def _next(self) -> dict | None:
        """アプリが送った次のメッセージ。アプリが何も送らずに終わったら None。"""
        while True:
            if not self._from_app.empty():
                return self._from_app.get_nowait()
            if self._task.done():
                self._task.result()                       # 例外で終わっていれば、ここで送出される
                return None
            getter = asyncio.ensure_future(self._from_app.get())
            done, _ = await asyncio.wait({getter, self._task}, return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                return getter.result()
            getter.cancel()

    async def send_text(self, text: str) -> None:
        self._to_app.put_nowait({"type": "websocket.receive", "text": text})

    async def send_bytes(self, data: bytes) -> None:
        self._to_app.put_nowait({"type": "websocket.receive", "bytes": data})

    async def receive(self) -> str | bytes | None:
        """次のメッセージ（テキストは str、バイナリは bytes）。接続が閉じたら None。"""
        if not self.accepted or self.close_code is not None:
            return None
        msg = await self._next()
        if msg is None:
            return None
        if msg["type"] == "websocket.close":
            self.close_code = msg.get("code", 1000)
            return None
        return msg["text"] if msg.get("text") is not None else msg["bytes"]
