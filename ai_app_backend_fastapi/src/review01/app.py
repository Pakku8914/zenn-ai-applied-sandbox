"""復習1：レシピを指定して AI に相談する POST /api/suggest（S02〜S04 の部品を1つのアプリにまとめる）。

起動：APP_MODULE=src.review01.app:app docker compose up -d --wait api
上流は LLM_PROVIDER=anthropic|openai で切り替える（session04 と同じ）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Path, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from kondate.settings import get_settings

from .errors import ApiError, install_error_handlers
from .providers import ChatRequest, LLMProvider, open_provider
from .store import DataStore

logger = logging.getLogger("kondate.review01")

# 「プロバイダを開いて、抜けるときに閉じる」もの。テストでは mockllm や Fake に向けたものを渡す
ProviderFactory = Callable[[], AbstractAsyncContextManager[LLMProvider]]


class ProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    openai_model: str | None = None  # OpenAI 互換の上流で使うモデル ID（空なら LLM_MODEL）


def open_from_env() -> AbstractAsyncContextManager[LLMProvider]:
    ps = ProviderSettings()
    model = (ps.openai_model if ps.llm_provider == "openai" else None) or get_settings().llm_model
    # 接続先とキーは環境変数から SDK が読む。リトライは再試行のセッションで設計するまで 0 にしておく
    return open_provider(ps.llm_provider, model=model, timeout=30.0, max_retries=0)


# ---------------------------------------------------------------- 入出力の型


class RecipeOut(BaseModel):
    id: str
    name: str
    minutes: int


class SuggestIn(BaseModel):
    """POST /api/suggest の本文。知らない項目（temperature など）は 422 にする。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recipe_id: str = Field(pattern=r"^R\d{3}$")
    question: str = Field(min_length=1, max_length=500)


class UsageOut(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class SuggestOut(BaseModel):
    answer: str
    stop_reason: str
    provider: str
    usage: UsageOut
    request_id: str  # こちらの request_id。上流のリクエスト ID はログにだけ残す


# ---------------------------------------------------------------- 依存（モジュール直下に置く）


def get_store(request: Request) -> DataStore:
    return request.app.state.store


def get_provider(request: Request) -> LLMProvider:
    return request.app.state.provider


StoreDep = Annotated[DataStore, Depends(get_store)]
ProviderDep = Annotated[LLMProvider, Depends(get_provider)]


# ---------------------------------------------------------------- アプリ


def create_app(open_llm: ProviderFactory = open_from_env) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.store = DataStore.load()
        async with open_llm() as provider:  # プロセスに1つ。抜けるときに SDK のクライアント（接続プール）を閉じる
            app.state.provider = provider
            yield

    app = FastAPI(title="こんだてAI（復習1）", lifespan=lifespan)
    install_error_handlers(app)

    @app.get("/health")
    async def health(store: StoreDep) -> dict[str, object]:
        return {"status": "ok", "recipes": len(store.recipes)}

    @app.get("/api/recipes/{recipe_id}", response_model=RecipeOut)
    async def get_recipe(recipe_id: Annotated[str, Path(pattern=r"^R\d{3}$")], store: StoreDep) -> dict:
        recipe = store.get_recipe(recipe_id)
        if recipe is None:
            raise ApiError(404, "not_found", f"レシピが見つかりません：{recipe_id}")
        return recipe

    @app.post("/api/suggest", response_model=SuggestOut)
    async def suggest(body: SuggestIn, request: Request, store: StoreDep, provider: ProviderDep) -> SuggestOut:
        recipe = store.get_recipe(body.recipe_id)
        if recipe is None:  # LLM を呼ぶ前に断る（呼べばトークン代がかかる）
            raise ApiError(404, "not_found", f"レシピが見つかりません：{body.recipe_id}")
        result = await provider.complete(ChatRequest(
            messages=[{"role": "user", "content": body.question}],
            system=f"利用者は「{recipe['name']}」（調理時間 {recipe['minutes']} 分）を作ろうとしています。短く答えてください。",
            max_tokens=get_settings().llm_max_tokens,
        ))
        logger.info("suggest ok request_id=%s provider=%s upstream_request_id=%s input_tokens=%d output_tokens=%d",
                    request.state.request_id, provider.name, result.request_id or "-",
                    result.usage.input_tokens, result.usage.output_tokens)
        return SuggestOut(answer=result.text, stop_reason=result.stop_reason, provider=provider.name,
                          usage=UsageOut(**asdict(result.usage)), request_id=request.state.request_id)

    return app


app = create_app()
