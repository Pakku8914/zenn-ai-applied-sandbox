"""共通のエラー本文。review01/errors.py のコピーに、ストリーム途中の失敗の種別を決める関数を足したもの。

- ストリーム開始前：ProviderError → KIND_TO_ERROR → JSON のエラー本文（例外ハンドラ）
- ストリーム開始後：同じ KIND_TO_ERROR で種別だけを決め、error イベント {type, message, request_id} にする
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

from .providers import ProviderError

logger = logging.getLogger("kondate.session06.errors")

REQUEST_ID_HEADER = "x-request-id"
DEFAULT_RETRY_AFTER = 5  # 上流が秒数を示さなかったときにクライアントへ伝える待ち時間

# クライアントに見せる文は、ここに書いた日本語の固定文だけ。上流の生のエラー文は使わない
MESSAGES = {
    "rate_limited": "ただいま混み合っています。しばらく待ってから再度お試しください。",
    "upstream_timeout": "AI の応答が時間内に返りませんでした。時間をおいて再度お試しください。",
    "upstream_unavailable": "AI が一時的に利用できません。時間をおいて再度お試しください。",
    "upstream_error": "AI の呼び出しに失敗しました。",
    "not_found": "指定された URL は存在しません",
    "internal_error": "サーバー内部でエラーが発生しました",
}

# ProviderError.kind → (HTTP ステータス, API の種別)。どの SDK の失敗も、この表1つで形が決まる
KIND_TO_ERROR: dict[str, tuple[int, str]] = {
    "rate_limited": (429, "rate_limited"),
    "timeout": (504, "upstream_timeout"),
    "connection": (503, "upstream_unavailable"),
    "overloaded": (503, "upstream_unavailable"),
    "server_error": (503, "upstream_unavailable"),
    "auth": (502, "upstream_error"),
    "bad_request": (502, "upstream_error"),
    "bad_response": (502, "upstream_error"),
    "unsupported": (500, "internal_error"),  # 上流へ送る前にこちらが断った＝こちらの設定か実装の問題
}
FALLBACK_ERROR = (502, "upstream_error")  # 表に無い kind（stream_error など）


def stream_error_type(exc: Exception) -> str:
    """ストリームの途中で起きた失敗の種別。ステータスはもう変えられないので、種別だけを表から引く。"""
    if isinstance(exc, ProviderError):
        return KIND_TO_ERROR.get(exc.kind, FALLBACK_ERROR)[1]
    return "internal_error"  # 想定外の例外。例外の文はクライアントへ出さない


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
    """ルートから raise する例外。message を省くと種別ごとの固定文になる。"""

    def __init__(self, status_code: int, type: str, message: str | None = None,
                 headers: Mapping[str, str] | None = None) -> None:
        super().__init__(type)
        self.status_code = status_code
        self.type = type
        self.message = message or MESSAGES[type]
        self.headers = dict(headers or {})


def from_provider_error(e: ProviderError) -> ApiError:
    """ProviderError を API のエラーにする。retry-after は 429 のときだけ付ける。"""
    status, type_ = KIND_TO_ERROR.get(e.kind, FALLBACK_ERROR)
    headers = {"retry-after": str(e.retry_after or DEFAULT_RETRY_AFTER)} if type_ == "rate_limited" else None
    return ApiError(status, type_, headers=headers)


def error_response(request: Request, status_code: int, type: str, message: str,
                   headers: Mapping[str, str] | None = None) -> JSONResponse:
    rid = get_request_id(request)
    body = {"error": {"type": type, "message": message, "request_id": rid}}
    return JSONResponse(body, status_code=status_code, headers={**(headers or {}), REQUEST_ID_HEADER: rid})


_HTTP_ERRORS: dict[int, tuple[str, str]] = {
    401: ("unauthorized", "認証が必要です"),
    404: ("not_found", "指定された URL は存在しません"),
    405: ("invalid_request", "この URL では、そのメソッドは使えません"),
}


def _field_names(exc: RequestValidationError) -> list[str]:
    """('body', 'message') → message のように、どの入力が悪いかだけを取り出す。"""
    names: list[str] = []
    for err in exc.errors():
        loc = tuple(err.get("loc", ()))
        name = ".".join(str(p) for p in loc[1:] if not isinstance(p, int)) or (str(loc[0]) if loc else "request")
        if name not in names:
            names.append(name)
    return names


async def _on_api_error(request: Request, exc: ApiError) -> JSONResponse:
    return error_response(request, exc.status_code, exc.type, exc.message, exc.headers)


async def _on_provider_error(request: Request, exc: ProviderError) -> JSONResponse:
    # 原因の調査に使う値はログにだけ残す。クライアントには固定文と自前の request_id だけを返す
    logger.warning("provider_error provider=%s kind=%s status=%s upstream_request_id=%s request_id=%s",
                   exc.provider, exc.kind, exc.status_code, exc.request_id or "-", get_request_id(request))
    api = from_provider_error(exc)
    return error_response(request, api.status_code, api.type, api.message, api.headers)


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
    app.add_exception_handler(ProviderError, _on_provider_error)
    app.add_exception_handler(StarletteHTTPException, _on_http_error)
    app.add_exception_handler(RequestValidationError, _on_validation_error)
    app.add_exception_handler(Exception, _on_unexpected)
