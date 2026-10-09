"""共通エラー本文と request_id（session07 の errors.py をコピーし、unauthorized を足したもの）。

この章は LLM を呼ばないので、ProviderError からの翻訳は持たない。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from ulid import ULID

logger = logging.getLogger("kondate.session09.errors")

# クライアントに見せる文は、ここに書いた日本語の固定文だけ
MESSAGES = {
    "unauthorized": "認証が必要です",
    "invalid_request": "リクエストの形式が正しくありません。",
    "not_found": "指定されたものが見つかりません。",
    "internal_error": "サーバー内部でエラーが発生しました",
}


def new_request_id() -> str:
    return f"req_{ULID()}"


class ApiError(Exception):
    """クライアントに返すエラー。message を省くと MESSAGES の固定文を使う。"""

    def __init__(self, status: int, type_: str, headers: dict[str, str] | None = None,
                 message: str | None = None) -> None:
        super().__init__(type_)
        self.status, self.type, self.headers = status, type_, headers or {}
        self.message = message or MESSAGES[type_]


def error_body(type_: str, request_id: str, message: str | None = None) -> dict:
    return {"error": {"type": type_, "message": message or MESSAGES[type_], "request_id": request_id}}


def error_response(request: Request, status: int, type_: str, headers: dict[str, str] | None = None,
                   message: str | None = None) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or new_request_id()
    return JSONResponse(error_body(type_, request_id, message), status_code=status,
                        headers={**(headers or {}), "x-request-id": request_id})


def _type_for(status: int) -> str:
    return {401: "unauthorized", 404: "not_found"}.get(status, "invalid_request")


def install_error_handling(app: FastAPI) -> None:
    @app.middleware("http")
    async def assign_request_id(request: Request,
                                call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request.state.request_id = new_request_id()
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        return response

    @app.exception_handler(ApiError)
    async def on_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc.status, exc.type, exc.headers, exc.message)

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 既定の 422 は入力値（input）をそのまま返す。キーが紛れ込んでも映らないよう固定文にする
        return error_response(request, 422, "invalid_request")

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(request, exc.status_code, _type_for(exc.status_code), dict(exc.headers or {}))

    @app.exception_handler(Exception)
    async def on_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unexpected_error request_id=%s", getattr(request.state, "request_id", "-"))
        return error_response(request, 500, "internal_error")
