"""セッション3のアプリ。起動：APP_MODULE=src.session03.app:app docker compose up -d --wait api"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import anthropic
from anthropic import AsyncAnthropic
from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, Field

from src.session03.config import LLMSettings, get_llm_settings
from src.session03.errors import install_error_handling
from src.session03.llm import Answer, ask_llm, make_client, setup_logging

# 入力中の候補表示のように「待たせられない」用途向け。接続 1 秒・それ以外 2 秒
QUICK_TIMEOUT = anthropic.Timeout(2.0, connect=1.0)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class UsageOut(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class AskResponse(BaseModel):
    answer: str
    stop_reason: str | None
    usage: UsageOut
    request_id: str


def get_llm(request: Request) -> AsyncAnthropic:
    return request.app.state.llm


def get_app_settings(request: Request) -> LLMSettings:
    return request.app.state.settings


def get_mock_headers(request: Request,
                     settings: Annotated[LLMSettings, Depends(get_app_settings)]) -> dict[str, str]:
    """障害注入用の x-mock-* だけを上流へ渡す。接続先が mockllm でなければ常に空。"""
    if not settings.forwards_mock_headers:
        return {}
    return {k: v for k, v in request.headers.items() if k.startswith("x-mock-")}


LLM = Annotated[AsyncAnthropic, Depends(get_llm)]
Settings = Annotated[LLMSettings, Depends(get_app_settings)]
MockHeaders = Annotated[dict[str, str], Depends(get_mock_headers)]


def to_response(answer: Answer, request: Request) -> AskResponse:
    return AskResponse(answer=answer.text, stop_reason=answer.stop_reason,
                       usage=UsageOut(**answer.usage), request_id=request.state.request_id)


def create_app(settings: LLMSettings | None = None) -> FastAPI:
    settings = settings or get_llm_settings()
    setup_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.llm = make_client(settings)  # プロセスに1つ。接続プールをリクエスト間で使い回す
        try:
            yield
        finally:
            await app.state.llm.close()  # 終了時にプールの接続を閉じる

    app = FastAPI(title="こんだてAI セッション3", lifespan=lifespan)
    app.state.settings = settings
    install_error_handling(app)

    @app.get("/health")  # compose の healthcheck が使う
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/ask", response_model=AskResponse)
    async def ask(body: AskRequest, request: Request, llm: LLM, cfg: Settings,
                  mock_headers: MockHeaders) -> AskResponse:
        answer = await ask_llm(llm, cfg, body.question,
                               request_id=request.state.request_id, extra_headers=mock_headers)
        return to_response(answer, request)

    @app.post("/api/ask/quick", response_model=AskResponse)
    async def ask_quick(body: AskRequest, request: Request, llm: LLM, cfg: Settings,
                        mock_headers: MockHeaders) -> AskResponse:
        quick = llm.with_options(timeout=QUICK_TIMEOUT)  # 接続プールは共有したまま、この呼び出しだけ短くする
        answer = await ask_llm(quick, cfg, body.question,
                               request_id=request.state.request_id, extra_headers=mock_headers)
        return to_response(answer, request)

    return app


app = create_app()
