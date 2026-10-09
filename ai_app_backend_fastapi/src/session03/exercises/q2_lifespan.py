"""問題2の解答：リクエストごとに作っていたクライアントを、lifespan で1つだけ作る形に直す。

生成関数 make_llm を引数で受け取るので、検証では「何回作られたか」を数えられる。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated

from anthropic import AsyncAnthropic
from fastapi import Depends, FastAPI, Request

from src.session03.app import AskRequest
from src.session03.config import LLMSettings


def get_llm(request: Request) -> AsyncAnthropic:
    return request.app.state.llm


def create_app(make_llm: Callable[[], AsyncAnthropic], settings: LLMSettings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.llm = make_llm()
        try:
            yield
        finally:
            await app.state.llm.close()

    app = FastAPI(lifespan=lifespan)

    @app.post("/api/ask")
    async def ask(body: AskRequest, llm: Annotated[AsyncAnthropic, Depends(get_llm)]) -> dict[str, str]:
        message = await llm.messages.create(
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            messages=[{"role": "user", "content": body.question}],
        )
        return {"answer": "".join(b.text for b in message.content if b.type == "text")}

    return app
