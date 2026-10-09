"""共通のエラー本文（API契約④）。session13/errors.py と session16/errors.py をまとめたもの。

- 開始前の失敗：{"error": {"type", "message", "request_id"}} の JSON（AI SDK はこの本文の文字列を error.message にする）
- 開始後の失敗：同じ種別表から type だけを決め、UI の error チャンク {errorText: 固定文} にする（chat.py）
- 想定外の例外（500）はミドルウェア（middleware.py）が JSON にする。Exception のハンドラはここで登録しない
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logctx import request_id_var
from .middleware import INTERNAL_ERROR_MESSAGE, REQUEST_ID_HEADER, new_request_id
from .providers import ProviderError

logger = logging.getLogger("kondate.final.errors")

DEFAULT_RETRY_AFTER = 5

# クライアントに見せる文は、ここに書いた日本語の固定文だけ。上流の生のエラー文は使わない
MESSAGES = {
    "unauthorized": "認証が必要です",
    "invalid_request": "リクエストの形式が正しくありません。",
    "not_found": "指定されたものが見つかりません。",
    "rate_limited": "ただいま混み合っています。しばらく待ってから再度お試しください。",
    "quota_exceeded": "本日の利用上限に達しました。日付が変わってから再度お試しください。",
    "budget_exceeded": "今月の利用予算に達しました。翌月になってから再度お試しください。",
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
    "breaker_open": (503, "upstream_unavailable"),  # Session 11：ブレーカが開いていて上流を呼ばなかった
    "auth": (502, "upstream_error"),
    "bad_request": (502, "upstream_error"),
    "bad_response": (502, "upstream_error"),
    "unsupported": (500, "internal_error"),
}
FALLBACK_ERROR = (502, "upstream_error")  # 表に無い kind（stream_error など）


class ApiError(Exception):
    """ルートや依存性から raise する例外。message を省くと種別ごとの固定文になる。"""

    def __init__(self, status_code: int, type: str, message: str | None = None,
                 headers: Mapping[str, str] | None = None) -> None:
        super().__init__(type)
        self.status_code = status_code
        self.type = type
        self.message = message or MESSAGES[type]
        self.headers = dict(headers or {})


class ServiceUnavailable(Exception):
    """このサーバーが新しい会話を受けられない（drain 中・同時ストリームが満員・drain の締め切り）。"""


def stream_error_type(exc: BaseException) -> str:
    """ストリームの途中で起きた失敗の種別。ステータスはもう変えられないので、種別だけを決める。"""
    if isinstance(exc, ProviderError):
        return KIND_TO_ERROR.get(exc.kind, FALLBACK_ERROR)[1]
    if isinstance(exc, ServiceUnavailable):
        return "service_unavailable"
    return "internal_error"


def from_provider_error(e: ProviderError) -> ApiError:
    status, type_ = KIND_TO_ERROR.get(e.kind, FALLBACK_ERROR)
    headers = {"retry-after": str(e.retry_after or DEFAULT_RETRY_AFTER)} if type_ == "rate_limited" else None
    return ApiError(status, type_, headers=headers)


def error_response(request: Request, status_code: int, type_: str, message: str,
                   headers: Mapping[str, str] | None = None) -> JSONResponse:
    rid = getattr(request.state, "request_id", None) or request_id_var.get() or new_request_id()
    body = {"error": {"type": type_, "message": message, "request_id": rid}}
    return JSONResponse(body, status_code=status_code, headers={**(headers or {}), REQUEST_ID_HEADER: rid})


_HTTP_ERRORS: dict[int, tuple[str, str]] = {
    401: ("unauthorized", MESSAGES["unauthorized"]),
    404: ("not_found", "指定された URL は存在しません"),
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


async def _on_provider_error(request: Request, exc: ProviderError) -> JSONResponse:
    # 原因の調査に使う値はログにだけ残す。クライアントには固定文と request_id だけを返す
    logger.warning("provider_error", extra={"provider": exc.provider, "kind": exc.kind, "status": exc.status_code,
                                            "upstream_request_id": exc.request_id})
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


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _on_api_error)
    app.add_exception_handler(ProviderError, _on_provider_error)
    app.add_exception_handler(StarletteHTTPException, _on_http_error)
    app.add_exception_handler(RequestValidationError, _on_validation_error)
