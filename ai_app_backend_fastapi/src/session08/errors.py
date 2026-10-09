"""共通エラー本文と request_id。session05 の素の ASGI ミドルウェア（SSE に割り込まない）に、
session07 の ProviderError からの翻訳を足したコピー。"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from ulid import ULID

from .providers import ProviderError

logger = logging.getLogger("kondate.session08.errors")

# クライアントに見せる文は、ここに書いた日本語の固定文だけ
MESSAGES = {
    "invalid_request": "リクエストの形式が正しくありません。",
    "not_found": "指定されたものが見つかりません。",
    "rate_limited": "ただいま混み合っています。しばらく待ってから再度お試しください。",
    "upstream_timeout": "AI の応答が時間内に返りませんでした。時間をおいて再度お試しください。",
    "upstream_unavailable": "AI が一時的に利用できません。時間をおいて再度お試しください。",
    "upstream_error": "AI の呼び出しに失敗しました。",
    "internal_error": "サーバー内部でエラーが発生しました",
}


def new_request_id() -> str:
    return f"req_{ULID()}"


def error_type_of(e: ProviderError) -> str:
    """ProviderError の kind を API契約のエラー種別に読み替える（session07 の from_provider_error と同じ表）。"""
    if e.kind == "rate_limited":
        return "rate_limited"
    if e.kind == "timeout":
        return "upstream_timeout"
    if e.kind in ("bad_request", "auth", "unsupported", "bad_response", "stream_error"):
        return "upstream_error"
    return "upstream_unavailable"


def error_payload(type_: str, request_id: str) -> dict:
    return {"type": type_, "message": MESSAGES[type_], "request_id": request_id}


class RequestIdMiddleware:
    """リクエストごとに req_+ULID を採番し、request.state と応答ヘッダ x-request-id に入れる。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = new_request_id()  # クライアントが送った ID は信用せず毎回採番する
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["x-request-id"] = request_id
            await send(message)

        await self.app(scope, receive, send_with_id)


def error_response(request: Request, status: int, type_: str) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or new_request_id()
    return JSONResponse({"error": error_payload(type_, request_id)}, status_code=status,
                        headers={"x-request-id": request_id})


def install_error_handling(app: FastAPI) -> None:
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(request, 422, "invalid_request")

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(request, exc.status_code, "not_found" if exc.status_code == 404 else "invalid_request")

    @app.exception_handler(Exception)
    async def on_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unexpected_error request_id=%s", getattr(request.state, "request_id", "-"))
        return error_response(request, 500, "internal_error")
