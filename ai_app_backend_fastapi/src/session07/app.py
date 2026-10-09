"""会話履歴を PostgreSQL に保存するチャット API。

起動：APP_MODULE=src.session07.app:app docker compose up -d --wait api
事前に：docker compose exec api alembic -c src/session07/alembic.ini upgrade head
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

import anthropic
from fastapi import Depends, FastAPI, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from kondate.db import engine
from kondate.settings import get_settings

from . import repo
from .deps import FactoryDep, SessionDep
from .errors import ApiError, error_body, from_provider_error, install_error_handling
from .history import ContextTooLong, Fitted, fit_history, fit_with_summary
from .models import new_id
from .providers import (AnthropicProvider, ChatRequest, LLMProvider, ProviderError, StreamEvent, TextDelta,
                        accumulate, assistant_message)
from .tokens import AnthropicTokenCounter, TokenCounter

logger = logging.getLogger("kondate.session07")
TOO_LONG_MESSAGE = "発言が長すぎて送れません。短くして送り直してください。"


class HistorySettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    history_max_input_tokens: int = 8000  # 履歴＋新しい発言に使ってよい入力トークン（コストの上限でもある）
    history_strategy: Literal["truncate", "summarize"] = "truncate"
    history_summary_tokens: int = 300  # 要約に使ってよい出力トークン
    history_on_failure: Literal["discard", "partial"] = "discard"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    client = anthropic.AsyncAnthropic(timeout=30.0)  # 接続先とキーは ANTHROPIC_* から読む
    app.state.provider = AnthropicProvider(client, default_model=s.llm_model)
    app.state.counter = AnthropicTokenCounter(client, model=s.llm_model)
    yield
    await client.close()
    await engine.dispose()


app = FastAPI(title="こんだてAI（会話履歴の永続化）", lifespan=lifespan)
install_error_handling(app)


def get_provider(request: Request) -> LLMProvider:
    return request.app.state.provider


def get_counter(request: Request) -> TokenCounter:
    return request.app.state.counter


def get_history_settings() -> HistorySettings:
    return HistorySettings()


ProviderDep = Annotated[LLMProvider, Depends(get_provider)]
CounterDep = Annotated[TokenCounter, Depends(get_counter)]
HistoryDep = Annotated[HistorySettings, Depends(get_history_settings)]


class ConversationIn(BaseModel):
    user_id: str = Field(pattern=r"^u\d{3}$")
    title: str | None = Field(default=None, max_length=200)


class ConversationOut(BaseModel):
    id: str
    user_id: str
    title: str | None


class MessageOut(BaseModel):
    id: str
    seq: int
    role: str
    content: list[dict]
    status: str


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/conversations", status_code=201)
async def create_conversation(body: ConversationIn, session: SessionDep) -> ConversationOut:
    conv = await repo.create_conversation(session, user_id=body.user_id, title=body.title)
    await session.commit()
    return ConversationOut(id=conv.id, user_id=conv.user_id, title=conv.title)


@app.get("/api/conversations/{conversation_id}")
async def show_conversation(conversation_id: UUID, session: SessionDep) -> ConversationDetail:
    conv = await repo.get_conversation(session, str(conversation_id))
    if conv is None:
        raise ApiError(404, "not_found")
    rows = await repo.load_messages(session, conv.id)
    return ConversationDetail(id=conv.id, user_id=conv.user_id, title=conv.title, messages=[
        MessageOut(id=r.id, seq=r.seq, role=r.role, content=r.content, status=r.status) for r in rows])


@dataclass(frozen=True)
class PreparedTurn:
    conversation_id: str
    user_content: list[dict]
    request: ChatRequest
    fitted: Fitted


async def prepare_turn(conversation_id: UUID, body: MessageIn, session: SessionDep, counter: CounterDep,
                       provider: ProviderDep, hs: HistoryDep) -> PreparedTurn:
    """ストリームを始める前の仕事。ここで失敗すれば、共通エラー本文（JSON）で返せる。"""
    conv = await repo.get_conversation(session, str(conversation_id))
    if conv is None:
        raise ApiError(404, "not_found")
    history = repo.to_api_messages(await repo.load_messages(session, conv.id))
    await session.commit()  # 読み取りのトランザクションを閉じて接続を返す（ストリーミング中に握らない）
    user_content = [{"type": "text", "text": body.content}]
    candidate = [*history, {"role": "user", "content": user_content}]
    try:
        if hs.history_strategy == "summarize":
            fitted = await fit_with_summary(candidate, counter, provider, budget=hs.history_max_input_tokens,
                                            summary_tokens=hs.history_summary_tokens,
                                            model=get_settings().llm_model_light)
        else:
            fitted = await fit_history(candidate, counter, budget=hs.history_max_input_tokens)
    except ContextTooLong:
        raise ApiError(422, "invalid_request", message=TOO_LONG_MESSAGE) from None
    except ProviderError as e:
        raise from_provider_error(e) from e
    request = ChatRequest(messages=fitted.messages, max_tokens=get_settings().llm_max_tokens)
    return PreparedTurn(conv.id, user_content, request, fitted)


def sse(name: str, payload: dict) -> ServerSentEvent:
    return ServerSentEvent(event=name, raw_data=json.dumps(payload, ensure_ascii=False))


async def save_turn(factory: async_sessionmaker[AsyncSession], turn: PreparedTurn, assistant_id: str,
                    content: list[dict], status: str) -> bool:
    """1往復を1つのトランザクションで保存する。ストリーミングの後なので、短い専用のセッションを開く。"""
    try:
        async with factory() as session:
            await repo.append_turn(session, turn.conversation_id, user_content=turn.user_content,
                                   assistant_content=content, assistant_id=assistant_id, status=status)
            await session.commit()
    except SQLAlchemyError:
        logger.exception("save_turn_failed conversation_id=%s", turn.conversation_id)
        return False
    return True


@app.post("/api/conversations/{conversation_id}/messages", response_class=EventSourceResponse)
async def post_message(request: Request, turn: Annotated[PreparedTurn, Depends(prepare_turn)],
                       provider: ProviderDep, factory: FactoryDep,
                       hs: HistoryDep) -> AsyncIterator[ServerSentEvent]:
    request_id = request.state.request_id
    message_id = new_id()  # 保存する assistant の発言の ID を先に決めて、start で知らせる
    yield sse("start", {"message_id": message_id})
    events: list[StreamEvent] = []
    try:
        async for ev in provider.stream(turn.request):
            events.append(ev)
            if isinstance(ev, TextDelta):
                yield sse("delta", {"text": ev.text})
    except ProviderError as e:
        logger.warning("stream_failed kind=%s upstream_request_id=%s request_id=%s",
                       e.kind, e.request_id, request_id)
        partial = "".join(ev.text for ev in events if isinstance(ev, TextDelta))
        if hs.history_on_failure == "partial" and partial:
            await save_turn(factory, turn, message_id, [{"type": "text", "text": partial}], "partial")
        yield sse("error", error_body(from_provider_error(e).type, request_id)["error"])
        return
    result = accumulate(events)
    if not await save_turn(factory, turn, message_id, assistant_message(result)["content"], "complete"):
        yield sse("error", error_body("internal_error", request_id)["error"])
        return
    # 保存できてから usage と done を送る（done を受け取った時点で、履歴に残っていることを保証する）
    yield sse("usage", {"input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens})
    yield sse("done", {"stop_reason": result.stop_reason})
