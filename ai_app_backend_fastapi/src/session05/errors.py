"""共通エラー本文と request_id。Session 3 の errors.py をストリーミング向けに手直ししたコピー（この章で使う部分だけ）。

request_id を付ける部分は、@app.middleware("http")（BaseHTTPMiddleware）ではなく、Session 2 の
素の ASGI ミドルウェアに戻した。応答本文を1つずつ素通しするので、SSE の送出と切断の検知に割り込まない。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from ulid import ULID

logger = logging.getLogger("kondate.session05.errors")

# クライアントに見せる文は、ここに書いた日本語の固定文だけ
MESSAGES = {
    "internal_error": "サーバー内部でエラーが発生しました",
}

_HTTP_ERRORS: dict[int, tuple[str, str]] = {
    404: ("not_found", "指定された URL は存在しません"),
    405: ("invalid_request", "この URL では、そのメソッドは使えません"),
}


def new_request_id() -> str:
    return f"req_{ULID()}"


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


def error_response(request: Request, status: int, type_: str, message: str) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or new_request_id()
    body = {"error": {"type": type_, "message": message, "request_id": request_id}}
    return JSONResponse(body, status_code=status, headers={"x-request-id": request_id})


def _field_names(exc: RequestValidationError) -> list[str]:
    """('body', 'message') → message のように、どの入力が悪いかだけを取り出す。"""
    names: list[str] = []
    for err in exc.errors():
        loc = tuple(err.get("loc", ()))
        name = ".".join(str(p) for p in loc[1:] if not isinstance(p, int)) or (str(loc[0]) if loc else "request")
        if name not in names:
            names.append(name)
    return names


def install_error_handling(app: FastAPI) -> None:
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = "、".join(_field_names(exc))
        return error_response(request, 422, "invalid_request", f"入力値が正しくありません：{fields}")

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        type_, message = _HTTP_ERRORS.get(exc.status_code, ("invalid_request", "リクエストを処理できませんでした"))
        return error_response(request, exc.status_code, type_, message)

    @app.exception_handler(Exception)
    async def on_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unexpected_error request_id=%s", getattr(request.state, "request_id", "-"))
        return error_response(request, 500, "internal_error", MESSAGES["internal_error"])
