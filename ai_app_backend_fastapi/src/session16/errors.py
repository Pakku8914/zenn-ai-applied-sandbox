"""共通のエラー本文（session14/errors.py のコピーに、次の2つを足したもの）。

- service_unavailable：このサーバーが「いまは新しい会話を受けない」状態（止める途中の drain・1ワーカーの同時ストリームが満員）。
  上流（LLM）の不調を表す upstream_unavailable とは分ける。別のサーバーなら受けられるので、クライアントはやり直してよい
- stream_error_type()：ストリームの途中で起きた例外から、error イベントの種別だけを決める
"""

from __future__ import annotations

from collections.abc import Mapping

import anthropic
import httpx2
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logctx import request_id_var
from .middleware import INTERNAL_ERROR_MESSAGE, REQUEST_ID_HEADER, new_request_id

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


class ApiError(Exception):
    def __init__(self, status: int, type_: str, headers: Mapping[str, str] | None = None) -> None:
        super().__init__(type_)
        self.status, self.type, self.headers = status, type_, dict(headers or {})


def translate(exc: anthropic.APIError) -> ApiError:
    """SDK の例外をこちらの API のエラーに翻訳する。子クラスから先に判定する。"""
    if isinstance(exc, anthropic.RateLimitError):
        retry_after = exc.response.headers.get("retry-after", "")
        return ApiError(429, "rate_limited", {"retry-after": retry_after if retry_after.isdigit() else "5"})
    if isinstance(exc, anthropic.APITimeoutError):
        return ApiError(504, "upstream_timeout")
    if isinstance(exc, anthropic.APIConnectionError):
        return ApiError(503, "upstream_unavailable")
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
        return ApiError(503, "upstream_unavailable")
    return ApiError(502, "upstream_error")


def stream_error_type(exc: BaseException) -> str:
    """ストリームの途中の失敗の種別。ステータスはもう変えられないので、種別だけを決める。"""
    if isinstance(exc, anthropic.APIError):
        return translate(exc).type
    if isinstance(exc, httpx2.HTTPError):  # 上流の途中切断（RemoteProtocolError）など
        return "upstream_unavailable"
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
