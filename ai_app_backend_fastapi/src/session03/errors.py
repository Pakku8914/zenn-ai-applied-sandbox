"""共通エラー本文・request_id の採番・SDK の例外の翻訳。上流の生の文はクライアントに返さない。

session02/errors.py に、上流の種別の固定文（MESSAGES）と SDK の例外の翻訳（translate）を足したもの。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping

import anthropic
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from ulid import ULID

logger = logging.getLogger("kondate.session03.errors")

# 上流（LLM）に関わる種別と 500 の固定文。上流の生のエラー文は使わない
MESSAGES = {
    "rate_limited": "ただいま混み合っています。しばらく待ってから再度お試しください。",
    "upstream_timeout": "AI の応答が時間内に返りませんでした。時間をおいて再度お試しください。",
    "upstream_unavailable": "AI が一時的に利用できません。時間をおいて再度お試しください。",
    "upstream_error": "AI の呼び出しに失敗しました。",
    "internal_error": "サーバー内部でエラーが発生しました",
}

_HTTP_ERRORS: dict[int, tuple[str, str]] = {
    401: ("unauthorized", "認証が必要です"),
    404: ("not_found", "指定された URL は存在しません"),
    405: ("invalid_request", "この URL では、そのメソッドは使えません"),
}


def new_request_id() -> str:
    return f"req_{ULID()}"


class ApiError(Exception):
    """ルートから raise する例外。message を省くと種別ごとの固定文（MESSAGES）になる。"""

    def __init__(self, status_code: int, type: str, message: str | None = None,
                 headers: Mapping[str, str] | None = None) -> None:
        super().__init__(type)
        self.status_code = status_code
        self.type = type
        self.message = message or MESSAGES[type]
        self.headers = dict(headers or {})


def error_response(request: Request, status_code: int, type: str, message: str,
                   headers: Mapping[str, str] | None = None) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or new_request_id()
    body = {"error": {"type": type, "message": message, "request_id": request_id}}
    return JSONResponse(body, status_code=status_code, headers={**(headers or {}), "x-request-id": request_id})


def _field_names(exc: RequestValidationError) -> list[str]:
    """('body', 'question') → question のように、どの入力が悪いかだけを取り出す。"""
    names: list[str] = []
    for err in exc.errors():
        loc = tuple(err.get("loc", ()))
        name = ".".join(str(p) for p in loc[1:] if not isinstance(p, int)) or (str(loc[0]) if loc else "request")
        if name not in names:
            names.append(name)
    return names


def translate(exc: anthropic.APIError) -> ApiError:
    """SDK の例外をこちらの API のエラーに翻訳する。子クラスから先に判定する。"""
    if isinstance(exc, anthropic.RateLimitError):  # 429。retry-after は秒数のときだけ伝える
        retry_after = exc.response.headers.get("retry-after", "")
        return ApiError(429, "rate_limited", headers={"retry-after": retry_after if retry_after.isdigit() else "5"})
    if isinstance(exc, anthropic.APITimeoutError):  # APIConnectionError の子なので先に見る
        return ApiError(504, "upstream_timeout")
    if isinstance(exc, anthropic.APIConnectionError):  # 名前解決の失敗・接続拒否など
        return ApiError(503, "upstream_unavailable")
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:  # 500・529 など
        return ApiError(503, "upstream_unavailable")
    return ApiError(502, "upstream_error")  # 400・401・404 など：こちらの不具合か設定ミス


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
        return error_response(request, exc.status_code, exc.type, exc.message, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = "、".join(_field_names(exc))
        return error_response(request, 422, "invalid_request", f"入力値が正しくありません：{fields}")

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code >= 500:
            type_, message = "internal_error", MESSAGES["internal_error"]
        else:
            type_, message = _HTTP_ERRORS.get(exc.status_code, ("invalid_request", "リクエストを処理できませんでした"))
        return error_response(request, exc.status_code, type_, message, exc.headers)

    @app.exception_handler(Exception)
    async def on_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unexpected_error request_id=%s", getattr(request.state, "request_id", "-"))
        return error_response(request, 500, "internal_error", MESSAGES["internal_error"])
