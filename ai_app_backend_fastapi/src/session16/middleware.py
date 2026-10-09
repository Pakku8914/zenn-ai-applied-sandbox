"""リクエストID のミドルウェア（session14/middleware.py のコピー）。

session14 から変えた点：
- 既定を trust_incoming=False にした（受け取った x-request-id は使わず毎回採番する。台帳の一意キーと衝突させないため）
- request_finished を出さない既定のパスに /ready を足した（数秒ごとに来るので）
"""

from __future__ import annotations

import json
import logging
import re
import time

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from ulid import ULID

from .logctx import request_id_var

REQUEST_ID_HEADER = "x-request-id"
REQUEST_ID_RE = re.compile(r"req_[0-9A-HJKMNP-TV-Z]{26}")
INTERNAL_ERROR_MESSAGE = "サーバー内部でエラーが発生しました"

access_logger = logging.getLogger("kondate.session16.access")
error_logger = logging.getLogger("kondate.session16.errors")


def new_request_id() -> str:
    return f"req_{ULID()}"


def choose_request_id(incoming: str | None) -> tuple[str, str]:
    if incoming is None:
        return new_request_id(), "generated"
    if REQUEST_ID_RE.fullmatch(incoming):
        return incoming, "received"
    return new_request_id(), "rejected"


def _incoming(scope: Scope) -> str | None:
    for name, value in scope["headers"]:
        if name == b"x-request-id":
            return value.decode("latin-1")
    return None


async def send_internal_error(send: Send, request_id: str) -> None:
    body = json.dumps({"error": {"type": "internal_error", "message": INTERNAL_ERROR_MESSAGE,
                                 "request_id": request_id}}, ensure_ascii=False).encode("utf-8")
    await send({"type": "http.response.start", "status": 500,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp, *, trust_incoming: bool = False,
                 skip_paths: frozenset[str] = frozenset({"/health", "/ready"})) -> None:
        self.app = app
        self.trust_incoming = trust_incoming
        self.skip_paths = skip_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid, source = choose_request_id(_incoming(scope) if self.trust_incoming else None)
        scope.setdefault("state", {})["request_id"] = rid
        token = request_id_var.set(rid)
        started = time.perf_counter()
        status: int | None = None

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = rid
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            error_logger.exception("unhandled_error")
            if status is not None:
                raise
            await send_internal_error(send_with_id, rid)
        finally:
            if scope["path"] not in self.skip_paths:
                access_logger.info("request_finished", extra={
                    "method": scope["method"], "path": scope["path"], "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "request_id_source": source})
            request_id_var.reset(token)
