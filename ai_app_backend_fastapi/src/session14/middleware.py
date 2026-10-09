"""リクエストID のミドルウェア（session05/errors.py の RequestIdMiddleware を手直ししたコピー）。

素の ASGI で書く（BaseHTTPMiddleware にしない）。応答本文を1つずつ素通しするので、SSE の送出と切断の検知に割り込まない。
session05 から変えた点：
- x-request-id を受け取り、形式（req_ + ULID）が正しければそのまま使う。無い・不正なら採番する
- 決めた ID を contextvars（request_id_var）にも入れる。この中で出したログには自動で request_id が付く
- 1リクエストにつき1行、request_finished（method・path・status・duration_ms）を出す
- 想定外の例外もここで受け、request_id の付いたログを残してから 500 を返す
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
REQUEST_ID_RE = re.compile(r"req_[0-9A-HJKMNP-TV-Z]{26}")  # req_ + ULID（Crockford の Base32・26文字）
INTERNAL_ERROR_MESSAGE = "サーバー内部でエラーが発生しました"

access_logger = logging.getLogger("kondate.session14.access")
error_logger = logging.getLogger("kondate.session14.errors")


def new_request_id() -> str:
    return f"req_{ULID()}"


def choose_request_id(incoming: str | None) -> tuple[str, str]:
    """(使う ID, 出どころ) を返す。出どころは received（受け取った）/ generated（無いので採番）/ rejected（不正なので採番）。"""
    if incoming is None:
        return new_request_id(), "generated"
    if REQUEST_ID_RE.fullmatch(incoming):
        return incoming, "received"
    return new_request_id(), "rejected"  # 不正な値はログにも出さない（ログの改ざん・個人情報の持ち込みを防ぐ）


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
    def __init__(self, app: ASGIApp, *, trust_incoming: bool = True,
                 skip_paths: frozenset[str] = frozenset({"/health"})) -> None:
        self.app = app
        self.trust_incoming = trust_incoming  # False なら、受け取った値は見ずに毎回採番する
        self.skip_paths = skip_paths  # healthcheck は数秒ごとに来るので、request_finished を出さない

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
            error_logger.exception("unhandled_error")  # まだ request_id_var が入っているうちに残す
            if status is not None:
                raise  # 応答を始めた後は本文を差し替えられない（ストリームは error イベントで終える：Session 6）
            await send_internal_error(send_with_id, rid)
        finally:
            if scope["path"] not in self.skip_paths:
                # path にはクエリ文字列を含めない（?email=… のように個人情報が入りうる）
                access_logger.info("request_finished", extra={
                    "method": scope["method"], "path": scope["path"], "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "request_id_source": source})
            request_id_var.reset(token)
