"""プロバイダ差し替え層の上に載せた POST /api/ask。LLM_PROVIDER=anthropic|openai で上流を切り替える。

起動：APP_MODULE=src.session04.app:app docker compose up -d --wait api
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from ulid import ULID

from kondate.settings import get_settings

from .providers import ChatRequest, LLMProvider, ProviderError, open_provider

logger = logging.getLogger("kondate.session04")
UPSTREAM_MESSAGE = "AI が一時的に利用できません。時間をおいて再度お試しください。"


class ProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    openai_model: str | None = None  # OpenAI 互換の上流で使うモデル ID（空なら LLM_MODEL）


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ps = ProviderSettings()
    model = (ps.openai_model if ps.llm_provider == "openai" else None) or get_settings().llm_model
    # 接続先とキーは環境変数（ANTHROPIC_* / OPENAI_*）から SDK が読む。プロセスに1つ作り、終了時に閉じる
    # リトライはセッション11で設計するまで 0（S03 と同じ）
    async with open_provider(ps.llm_provider, model=model, timeout=30.0, max_retries=0) as provider:
        app.state.provider = provider
        yield


app = FastAPI(title="こんだてAI（プロバイダ差し替え層）", lifespan=lifespan)


def get_provider(request: Request) -> LLMProvider:
    return request.app.state.provider


def error_body(status: int, etype: str, message: str, request: Request) -> JSONResponse:
    return JSONResponse(status_code=status, content={
        "error": {"type": etype, "message": message, "request_id": request.state.request_id}})


@app.middleware("http")
async def add_request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    request.state.request_id = f"req_{ULID()}"
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, e: RequestValidationError) -> JSONResponse:
    # ('body', 'question') → question のように、どの入力が悪いかだけを並べる
    fields = dict.fromkeys(".".join(str(p) for p in err["loc"][1:] if not isinstance(p, int)) for err in e.errors())
    return error_body(422, "invalid_request", f"入力値が正しくありません：{'、'.join(fields)}", request)


@app.exception_handler(ProviderError)
async def on_provider_error(request: Request, e: ProviderError) -> JSONResponse:
    # どの SDK の例外も ProviderError になっているので、ハンドラは1つで済む。生のエラー文は返さない
    logger.warning("provider_error provider=%s kind=%s status=%s upstream_request_id=%s request_id=%s",
                   e.provider, e.kind, e.status_code, e.request_id, request.state.request_id)
    return error_body(503, "upstream_unavailable", UPSTREAM_MESSAGE, request)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AskOut(BaseModel):
    answer: str
    stop_reason: str
    provider: str
    usage: dict[str, int]
    request_id: str


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/ask")
async def ask(body: AskIn, request: Request, provider: Annotated[LLMProvider, Depends(get_provider)]) -> AskOut:
    result = await provider.complete(ChatRequest(
        messages=[{"role": "user", "content": body.question}], max_tokens=get_settings().llm_max_tokens))
    # 上流のリクエスト ID はログにだけ残し、応答にはこちらで採番した request_id を載せる
    logger.info("llm_call ok request_id=%s provider=%s upstream_request_id=%s",
                request.state.request_id, provider.name, result.request_id or "-")
    return AskOut(answer=result.text, stop_reason=result.stop_reason, provider=provider.name,
                  usage=asdict(result.usage), request_id=request.state.request_id)
