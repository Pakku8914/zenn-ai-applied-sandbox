"""共通のエラー本文（session10/errors.py のコピーから、プロバイダ差し替え層に関わる部分を除いたもの）。

この章は LLM を呼ばないので、ProviderError の翻訳は持たない。固定文と request_id の採番だけを使う。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from ulid import ULID

logger = logging.getLogger("kondate.session12.errors")

REQUEST_ID_HEADER = "x-request-id"

# クライアントに見せる文は、ここに書いた日本語の固定文だけ
MESSAGES = {
    "unauthorized": "認証が必要です",
    "invalid_request": "リクエストの形式が正しくありません。",
    "rate_limited": "ただいま混み合っています。しばらく待ってから再度お試しください。",
    "not_found": "指定された URL は存在しません",
    "internal_error": "サーバー内部でエラーが発生しました",
}


def new_request_id() -> str:
    return f"req_{ULID()}"


def get_request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    if rid is None:
        rid = new_request_id()
        request.state.request_id = rid
    return rid


class RequestIdMiddleware:
    """リクエストごとに request_id を採番し、request.state と応答ヘッダに載せる（素の ASGI で書く）。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = new_request_id()
        scope.setdefault("state", {})["request_id"] = rid

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = rid
            await send(message)

        await self.app(scope, receive, send_with_id)


class ApiError(Exception):
    """ルートや依存性から raise する例外。message を省くと種別ごとの固定文になる。"""

    def __init__(self, status_code: int, type: str, message: str | None = None,
                 headers: Mapping[str, str] | None = None) -> None:
        super().__init__(type)
        self.status_code = status_code
        self.type = type
        self.message = message or MESSAGES[type]
        self.headers = dict(headers or {})


def error_response(request: Request, status_code: int, type: str, message: str,
                   headers: Mapping[str, str] | None = None) -> JSONResponse:
    rid = get_request_id(request)
    body = {"error": {"type": type, "message": message, "request_id": rid}}
    return JSONResponse(body, status_code=status_code, headers={**(headers or {}), REQUEST_ID_HEADER: rid})


_HTTP_ERRORS: dict[int, tuple[str, str]] = {
    401: ("unauthorized", MESSAGES["unauthorized"]),
    404: ("not_found", MESSAGES["not_found"]),
    405: ("invalid_request", "この URL では、そのメソッドは使えません"),
}


def _field_names(exc: RequestValidationError) -> list[str]:
    names: list[str] = []
    for err in exc.errors():
        loc = tuple(err.get("loc", ()))
        name = ".".join(str(p) for p in loc[1:] if not isinstance(p, int)) or (str(loc[0]) if loc else "request")
        if name not in names:
            names.append(name)
    return names


async def _on_api_error(request: Request, exc: ApiError) -> JSONResponse:
    return error_response(request, exc.status_code, exc.type, exc.message, exc.headers)


async def _on_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code >= 500:
        type_, message = "internal_error", MESSAGES["internal_error"]
    else:
        type_, message = _HTTP_ERRORS.get(exc.status_code, ("invalid_request", "リクエストを処理できませんでした"))
    return error_response(request, exc.status_code, type_, message, exc.headers)


async def _on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = "、".join(_field_names(exc))
    return error_response(request, 422, "invalid_request", f"入力値が正しくありません：{fields}")


async def _on_unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("想定外のエラー request_id=%s", get_request_id(request))
    return error_response(request, 500, "internal_error", MESSAGES["internal_error"])


def install_error_handlers(app: FastAPI) -> None:
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(ApiError, _on_api_error)
    app.add_exception_handler(StarletteHTTPException, _on_http_error)
    app.add_exception_handler(RequestValidationError, _on_validation_error)
    app.add_exception_handler(Exception, _on_unexpected)
