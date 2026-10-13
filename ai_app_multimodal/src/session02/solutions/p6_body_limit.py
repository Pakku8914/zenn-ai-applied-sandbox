"""問題6：本文を受け取る前に Content-Length で断る ASGI ミドルウェア。

    docker compose exec api python -m src.session02.solutions.p6_body_limit
    起動：APP_MODULE=src.session02.solutions.p6_body_limit:app docker compose up -d --wait api
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import httpx2
from fastapi.responses import JSONResponse
from PIL import Image
from ulid import ULID

from kondate.settings import get_settings
from src.session02 import app as session02

MiB = 1024 * 1024
MULTIPART_ALLOWANCE = 64 * 1024  # 区切り線やパートのヘッダーの分。ファイル本体の厳密な上限はエンドポイントが見る
OUT = Path("out/s02/solutions")


class RejectLargeBody:
    """Content-Length が上限を超えるリクエストを、本文を1バイトも読まずに 413 で返す。"""

    def __init__(self, app, max_body: int) -> None:
        self.app = app
        self.max_body = max_body

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            length = dict(scope["headers"]).get(b"content-length", b"")
            if length.isdigit() and int(length) > self.max_body:
                rid = f"req_{ULID()}"  # アプリ本体より外側なので、request_id もここで振る
                response = JSONResponse(
                    {"error": {"type": "too_large", "message": session02.MSG_TOO_LARGE, "request_id": rid}},
                    status_code=413,
                    headers={"x-request-id": rid, "connection": "close"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def wrap(inner) -> RejectLargeBody:
    return RejectLargeBody(inner, get_settings().upload_max_bytes + MULTIPART_ALLOWANCE)


app = wrap(session02.app)


class CountCalls:
    """内側のアプリが呼ばれた回数を数える（確認用）。"""

    def __init__(self, app) -> None:
        self.app = app
        self.calls = 0

    async def __call__(self, scope, receive, send) -> None:
        self.calls += 1
        await self.app(scope, receive, send)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, "PNG")
    return buf.getvalue()


async def _run() -> list[str]:
    session02.app.dependency_overrides[session02.upload_dir] = lambda: OUT
    limit = get_settings().upload_max_bytes
    cases = [
        ("12MiB のファイル", b"x" * (12 * MiB), "image/jpeg"),
        ("10MiB＋1バイトのファイル", b"x" * (limit + 1), "image/jpeg"),
        ("4×4 の PNG", _png(), "image/png"),
    ]
    lines = []
    for label, content, ctype in cases:
        inner = CountCalls(session02.app)
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=wrap(inner)), base_url="http://test") as c:
            r = await c.post("/api/uploads", files={"file": ("upload.bin", content, ctype)})
        status = f"{r.status_code} {r.json()['error']['type']}" if r.status_code >= 400 else f"{r.status_code}"
        lines.append(f"{label} → {status}（アプリ本体の呼び出し {inner.calls} 回）")
    return lines


def run() -> list[str]:
    return asyncio.run(_run())


if __name__ == "__main__":
    print("\n".join(run()))
