"""共通のエラー本文（session11/errors.py の種別の表と、session16/errors.py の service_unavailable を合わせたもの）。

- ProviderError.kind → (HTTP ステータス, 種別) は KIND_TO_ERROR の表1つで決める（セッション11）
- service_unavailable は「このサーバーがいま受け付けない」（drain 中）。上流の不調 upstream_unavailable とは分ける（セッション16）
- 想定外の例外の 500 はミドルウェアが返すので、Exception のハンドラは登録しない（セッション14）
"""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logctx import request_id_var
from .middleware import INTERNAL_ERROR_MESSAGE, REQUEST_ID_HEADER, new_request_id
from .providers import ProviderError

DEFAULT_RETRY_AFTER = 5

MESSAGES = {
    "invalid_request": "リクエストの形式が正しくありません。",
    "not_found": "指定された URL は存在しません",
    "rate_limited": "ただいま混み合っています。しばらく待ってから再度お試しください。",
    "upstream_timeout": "AI の応答が時間内に返りませんでした。時間をおいて再度お試しください。",
    "upstream_unavailable": "AI が一時的に利用できません。時間をおいて再度お試しください。",
    "upstream_error": "AI の呼び出しに失敗しました。",
    "service_unavailable": "このサーバーはいま新しい会話を受け付けていません。少し待ってから再度お試しください。",
    "internal_error": INTERNAL_ERROR_MESSAGE,
}

KIND_TO_ERROR: dict[str, tuple[int, str]] = {
    "rate_limited": (429, "rate_limited"),
    "timeout": (504, "upstream_timeout"),
    "connection": (503, "upstream_unavailable"),
    "overloaded": (503, "upstream_unavailable"),
    "server_error": (503, "upstream_unavailable"),
    "breaker_open": (503, "upstream_unavailable"),
    "auth": (502, "upstream_error"),
    "bad_request": (502, "upstream_error"),
    "bad_response": (502, "upstream_error"),
}
FALLBACK_ERROR = (502, "upstream_error")  # 表に無い kind（stream_error など）


class ApiError(Exception):
    def __init__(self, status: int, type_: str, headers: Mapping[str, str] | None = None) -> None:
        super().__init__(type_)
        self.status, self.type, self.headers = status, type_, dict(headers or {})


def from_provider_error(e: ProviderError) -> ApiError:
    status, type_ = KIND_TO_ERROR.get(e.kind, FALLBACK_ERROR)
    headers = {"retry-after": str(e.retry_after or DEFAULT_RETRY_AFTER)} if type_ == "rate_limited" else None
    return ApiError(status, type_, headers)


def stream_error_type(exc: BaseException) -> str:
    """ストリームの途中で起きた失敗の種別。ステータスはもう変えられないので、種別だけを表から引く。"""
    if isinstance(exc, ProviderError):
        return KIND_TO_ERROR.get(exc.kind, FALLBACK_ERROR)[1]
    return "internal_error"


def error_response(request: Request, status: int, type_: str,
                   headers: Mapping[str, str] | None = None) -> JSONResponse:
    rid = getattr(request.state, "request_id", None) or request_id_var.get() or new_request_id()
    body = {"error": {"type": type_, "message": MESSAGES[type_], "request_id": rid}}
    return JSONResponse(body, status_code=status, headers={**(headers or {}), REQUEST_ID_HEADER: rid})


async def _on_api_error(request: Request, exc: ApiError) -> JSONResponse:
    return error_response(request, exc.status, exc.type, exc.headers)


async def _on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(request, 422, "invalid_request")


async def _on_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    type_ = "not_found" if exc.status_code == 404 else "invalid_request"
    return error_response(request, exc.status_code, type_, exc.headers)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _on_api_error)
    app.add_exception_handler(RequestValidationError, _on_validation_error)
    app.add_exception_handler(StarletteHTTPException, _on_http_error)
