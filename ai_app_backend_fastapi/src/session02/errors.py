"""共通のエラー本文と request_id（後続のセッションはこのファイルをコピーして使う）。

    {"error": {"type": "<種別>", "message": "<日本語の固定文>", "request_id": "req_<ULID>"}}

- install_error_handlers(app) で、request_id の採番（応答ヘッダ x-request-id）と例外ハンドラをまとめて登録する
- ルートからは ApiError(status_code, type, message) を raise する
- 上流や内部の生のエラー文はクライアントに返さない（ログにだけ残す）
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from ulid import ULID

logger = logging.getLogger("kondate.errors")

REQUEST_ID_HEADER = "x-request-id"


def new_request_id() -> str:
    """req_ + ULID（26文字。時刻順に並ぶ）。"""
    return f"req_{ULID()}"


def get_request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    if rid is None:  # ミドルウェアを通らなかった場合の保険
        rid = new_request_id()
        request.state.request_id = rid
    return rid


class RequestIdMiddleware:
    """リクエストごとに request_id を採番し、request.state と応答ヘッダに載せる。

    BaseHTTPMiddleware ではなく素の ASGI で書く（後のセッションの SSE でも応答をためずに流せる）。
    """

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


class ErrorDetail(BaseModel):
    type: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    """OpenAPI（/docs）にエラー本文の形を載せるためのモデル。"""

    error: ErrorDetail


class ApiError(Exception):
    """ルートから raise する例外。type は API契約の種別（not_found・invalid_request など）。"""

    def __init__(
        self, status_code: int, type: str, message: str, headers: Mapping[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.type = type
        self.message = message
        self.headers = dict(headers or {})


def error_response(
    request: Request, status_code: int, type: str, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    rid = get_request_id(request)
    body = {"error": {"type": type, "message": message, "request_id": rid}}
    return JSONResponse(body, status_code=status_code, headers={**(headers or {}), REQUEST_ID_HEADER: rid})


_HTTP_ERRORS: dict[int, tuple[str, str]] = {
    401: ("unauthorized", "認証が必要です"),
    404: ("not_found", "指定された URL は存在しません"),
    405: ("invalid_request", "この URL では、そのメソッドは使えません"),
}


def _field_names(exc: RequestValidationError) -> list[str]:
    """('query', 'max_minutes') → max_minutes のように、どの入力が悪いかだけを取り出す。"""
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
        type_, message = "internal_error", "サーバー内部でエラーが発生しました"
    else:
        type_, message = _HTTP_ERRORS.get(exc.status_code, ("invalid_request", "リクエストを処理できませんでした"))
    return error_response(request, exc.status_code, type_, message, exc.headers)


async def _on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = "、".join(_field_names(exc))
    return error_response(request, 422, "invalid_request", f"入力値が正しくありません：{fields}")


async def _on_unexpected(request: Request, exc: Exception) -> JSONResponse:
    # 生のエラー文はログにだけ残し、クライアントには固定文と request_id だけを返す
    logger.exception("想定外のエラー request_id=%s", get_request_id(request))
    return error_response(request, 500, "internal_error", "サーバー内部でエラーが発生しました")


def install_error_handlers(app: FastAPI) -> None:
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(ApiError, _on_api_error)
    app.add_exception_handler(StarletteHTTPException, _on_http_error)
    app.add_exception_handler(RequestValidationError, _on_validation_error)
    app.add_exception_handler(Exception, _on_unexpected)
