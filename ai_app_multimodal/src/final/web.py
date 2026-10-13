"""ルーターで共通に使う小道具（各セッションの app.py に毎回書いていたものを1か所にまとめた）。"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from kondate.llm import LLMProvider, Usage
from kondate.settings import get_settings

settings = get_settings()
USER_ID_PATTERN = r"^u\d{3}$"
USER_ID_RE = re.compile(USER_ID_PATTERN)
RETRY_AFTER_SECONDS = 2

# 認証は①に任せ、ヘッダで代用する。省略時の既定は u001（DELETE /api/me/data だけは既定を使わない）
UserId = Annotated[str, Header(alias="x-user-id", pattern=USER_ID_PATTERN)]


def error(request: Request, status: int, type_: str, message: str, headers: dict | None = None) -> JSONResponse:
    """上流の生のエラー文は返さない。日本語の固定文と request_id だけを返す。"""
    return JSONResponse(
        {"error": {"type": type_, "message": message, "request_id": request.state.request_id}},
        status_code=status, headers=headers,
    )


def busy(request: Request, type_: str, message: str) -> JSONResponse:
    return error(request, 503, type_, message, {"retry-after": str(RETRY_AFTER_SECONDS)})


async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    names = dict.fromkeys(str(e["loc"][-1]) for e in exc.errors())
    return error(request, 422, "invalid_request", f"入力値が正しくありません：{'、'.join(names)}")


def get_llm(request: Request) -> LLMProvider:
    """使う LLM。verify・評価では dependency_overrides で差し替える。"""
    return request.app.state.llm


Llm = Annotated[LLMProvider, Depends(get_llm)]


def total(used: list[Usage]) -> Usage:
    return Usage(
        sum(u.input_tokens for u in used), sum(u.output_tokens for u in used),
        sum(u.cache_read_input_tokens for u in used), sum(u.cache_creation_input_tokens for u in used),
    )


def record_llm(request: Request, user_id: str, used: list[Usage]) -> None:
    """失敗した試行も含めて、実際に使ったトークンを記録する（セッション14）。"""
    if used:
        request.app.state.usage.add_llm(user_id, settings.llm_model, total(used), request.state.request_id)


def tokens2(u: Usage) -> dict:
    return {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens}


def tokens4(u: Usage) -> dict:
    return {**tokens2(u), "cache_creation_input_tokens": u.cache_creation_input_tokens,
            "cache_read_input_tokens": u.cache_read_input_tokens}
