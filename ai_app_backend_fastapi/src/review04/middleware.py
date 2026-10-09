"""リクエストID のミドルウェア（session16/middleware.py のコピーを、問題6で手直ししたもの）。

- request_id（応答ヘッダ x-request-id・エラー本文・台帳の一意キー）は、毎回このサーバが採番する
- 受け取った x-request-id は、形式（req_ + ULID）が正しいときだけ client_request_id として request_finished の行に残す。
  クライアント側のログとの突き合わせには使えるが、台帳のキーには使わない（同じ値を何度でも送れるため）
- trust_incoming=True は、セッション14の既定（受け取った値をそのまま request_id にする）。問題6で不具合を再現するために残している
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

access_logger = logging.getLogger("kondate.review04.access")
error_logger = logging.getLogger("kondate.review04.errors")


def new_request_id() -> str:
    return f"req_{ULID()}"


def valid_request_id(value: str | None) -> str | None:
    """形式が正しければその値、そうでなければ None（不正な値はログにも出さない）。"""
    return value if value is not None and REQUEST_ID_RE.fullmatch(value) else None


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
        incoming = valid_request_id(_incoming(scope))
        if self.trust_incoming and incoming is not None:
            rid, client_rid, source = incoming, None, "received"  # セッション14の既定：受け取った値を一意キーにもしてしまう
        else:
            rid, client_rid, source = new_request_id(), incoming, "generated"
        state = scope.setdefault("state", {})
        state["request_id"] = rid
        state["client_request_id"] = client_rid
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
                fields: dict[str, object] = {
                    "method": scope["method"], "path": scope["path"], "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1), "request_id_source": source}
                if client_rid is not None:
                    fields["client_request_id"] = client_rid  # 相関のためだけに残す（一意とは限らない）
                access_logger.info("request_finished", extra=fields)
            request_id_var.reset(token)
