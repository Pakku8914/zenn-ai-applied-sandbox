"""問題6の解答：quick のタイムアウトを設定から作り、with_options のコピーを lifespan で1回だけ用意する。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import anthropic
from anthropic import AsyncAnthropic
from fastapi import Depends, FastAPI, Request

from src.session03.app import LLM, AskRequest, AskResponse, MockHeaders, to_response
from src.session03.errors import install_error_handling
from src.session03.exercises.q1_settings import QuickSettings
from src.session03.llm import ask_llm, make_client, setup_logging


def quick_timeout(settings: QuickSettings) -> anthropic.Timeout:
    total = settings.llm_quick_timeout_seconds
    # 接続の上限が全体より長いと意味がないので、短いほうに揃える
    return anthropic.Timeout(total, connect=min(settings.llm_connect_timeout_seconds, total))


def get_quick_llm(request: Request) -> AsyncAnthropic:
    return request.app.state.llm_quick


QuickLLM = Annotated[AsyncAnthropic, Depends(get_quick_llm)]


def create_app(settings: QuickSettings) -> FastAPI:
    setup_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.llm = make_client(settings)
        # コピーは軽い（接続プールを共有する）。閉じるのは元の1つだけ
        app.state.llm_quick = app.state.llm.with_options(timeout=quick_timeout(settings))
        try:
            yield
        finally:
            await app.state.llm.close()

    app = FastAPI(lifespan=lifespan)
    app.state.settings = settings
    install_error_handling(app)

    @app.post("/api/ask", response_model=AskResponse)
    async def ask(body: AskRequest, request: Request, llm: LLM, mock_headers: MockHeaders) -> AskResponse:
        answer = await ask_llm(llm, settings, body.question,
                               request_id=request.state.request_id, extra_headers=mock_headers)
        return to_response(answer, request)

    @app.post("/api/ask/quick", response_model=AskResponse)
    async def ask_quick(body: AskRequest, request: Request, llm: QuickLLM,
                        mock_headers: MockHeaders) -> AskResponse:
        answer = await ask_llm(llm, settings, body.question,
                               request_id=request.state.request_id, extra_headers=mock_headers)
        return to_response(answer, request)

    return app
