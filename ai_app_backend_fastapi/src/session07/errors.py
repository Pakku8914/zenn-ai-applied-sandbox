"""共通エラー本文と request_id（session03 の errors.py をコピーし、ProviderError からの翻訳に差し替えたもの）。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from ulid import ULID

from .providers import ProviderError

logger = logging.getLogger("kondate.session07.errors")

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


class ApiError(Exception):
    """クライアントに返すエラー。message を省くと MESSAGES の固定文を使う（上流の文は決して入れない）。"""

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


def from_provider_error(e: ProviderError) -> ApiError:
    """ProviderError の kind を API契約のエラー種別に読み替える。"""
    if e.kind == "rate_limited":
        return ApiError(429, "rate_limited", {"retry-after": "5"})
    if e.kind == "timeout":
        return ApiError(504, "upstream_timeout")
    if e.kind in ("bad_request", "auth", "unsupported", "bad_response", "stream_error"):
        return ApiError(502, "upstream_error")  # こちらの不具合か設定ミス
    return ApiError(503, "upstream_unavailable")  # overloaded・server_error・connection


def install_error_handling(app: FastAPI) -> None:
    @app.middleware("http")
    async def assign_request_id(request: Request,
                                call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request.state.request_id = new_request_id()  # クライアントが送った ID は信用せず毎回採番する
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        return response

    @app.exception_handler(ApiError)
    async def on_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc.status, exc.type, exc.headers, exc.message)

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
