"""中間プロジェクト1：献立相談チャット API。会話を保存しながら、ツール付きの応答をストリーミングで返す。

起動：
    docker compose exec api alembic -c src/mid01/alembic.ini upgrade head
    APP_MODULE=src.mid01.app:app docker compose up -d --wait api

- POST /api/conversations                    … 会話を作る（持ち主は固定ユーザー u001。認証は Session 9）
- GET  /api/conversations/{id}               … 会話と発言（seq 順・status・stop_reason 付き）
- POST /api/conversations/{id}/messages      … 発言を送り、API契約③の SSE で応答を受け取る
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import anthropic
from fastapi import Depends, FastAPI, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from kondate.clock import SystemClock
from kondate.db import engine
from kondate.settings import get_settings

from . import repo
from .deps import FactoryDep, SessionDep
from .errors import ApiError, install_error_handlers
from .history import ContextTooLong, Fitted, fit_history, for_model, with_new_user
from .loop import ToolLimits
from .models import new_id
from .providers import AnthropicProvider, ChatRequest, LLMProvider
from .relay import PrimedLoop, TurnOutcome, prime_loop, relay_turn
from .tokens import AnthropicTokenCounter, TokenCounter
from .tools import ToolContext
from .turn import StoredMessage, TurnRecorder

logger = logging.getLogger("kondate.mid01")

SYSTEM = "あなたは献立相談AI「こんだてAI」です。レシピの情報は必ずツールで調べ、推測で答えないでください。"
FIXED_USER_ID = "u001"  # 認証は Session 9。それまでは全員を u001 として扱う
TOO_LONG_MESSAGE = "発言が長すぎて送れません。短くして送り直してください。"


class HistorySettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    history_max_input_tokens: int = 8000  # 履歴＋新しい発言に使ってよい入力トークン（コストの上限でもある）


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    # 接続先とキーは ANTHROPIC_BASE_URL・ANTHROPIC_API_KEY から読む。再試行は Session 11 で扱うので切っておく
    client = anthropic.AsyncAnthropic(timeout=30.0, max_retries=0)
    app.state.provider = AnthropicProvider(client, default_model=s.llm_model)
    app.state.counter = AnthropicTokenCounter(client, model=s.llm_model)
    try:
        yield
    finally:
        await client.close()
        await engine.dispose()


app = FastAPI(title="こんだてAI（献立相談チャット API）", lifespan=lifespan)
app.state.outcomes = deque(maxlen=100)  # 直近の往復の結末（検証で見る）
app.state.tool_context = ToolContext(clock=SystemClock())
app.state.limits = ToolLimits()
install_error_handlers(app)


def get_provider(request: Request) -> LLMProvider:
    return request.app.state.provider


def get_counter(request: Request) -> TokenCounter:
    return request.app.state.counter


def get_tool_context(request: Request) -> ToolContext:
    return request.app.state.tool_context


def get_limits(request: Request) -> ToolLimits:
    return request.app.state.limits


def get_history_settings() -> HistorySettings:
    return HistorySettings()


def get_user_id() -> str:
    return FIXED_USER_ID  # Session 9 で、API キーから引いたユーザーに差し替える


ProviderDep = Annotated[LLMProvider, Depends(get_provider)]
CounterDep = Annotated[TokenCounter, Depends(get_counter)]
ToolContextDep = Annotated[ToolContext, Depends(get_tool_context)]
LimitsDep = Annotated[ToolLimits, Depends(get_limits)]
HistoryDep = Annotated[HistorySettings, Depends(get_history_settings)]
UserIdDep = Annotated[str, Depends(get_user_id)]


class ConversationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # user_id を本文で受け取らない（送ってきたら 422）

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
    stop_reason: str | None


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4000)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/conversations", status_code=201)
async def create_conversation(body: ConversationIn, session: SessionDep, user_id: UserIdDep) -> ConversationOut:
    conv = await repo.create_conversation(session, user_id=user_id, title=body.title)
    await session.commit()
    return ConversationOut(id=conv.id, user_id=conv.user_id, title=conv.title)


@app.get("/api/conversations/{conversation_id}")
async def show_conversation(conversation_id: UUID, session: SessionDep) -> ConversationDetail:
    conv = await repo.get_conversation(session, str(conversation_id))
    if conv is None:
        raise ApiError(404, "not_found")
    rows = await repo.load_messages(session, conv.id)
    return ConversationDetail(id=conv.id, user_id=conv.user_id, title=conv.title, messages=[
        MessageOut(id=r.id, seq=r.seq, role=r.role, content=r.content, status=r.status, stop_reason=r.stop_reason)
        for r in rows])


@dataclass(frozen=True)
class PreparedTurn:
    conversation_id: str
    user_text: str
    request: ChatRequest
    fitted: Fitted


async def prepare_turn(conversation_id: UUID, body: MessageIn, session: SessionDep, counter: CounterDep,
                       hs: HistoryDep) -> PreparedTurn:
    """ストリームを始める前の仕事（会話の確認・履歴の読み出し・切り捨て）。ここでの失敗は JSON で返る。"""
    conv = await repo.get_conversation(session, str(conversation_id))
    if conv is None:
        raise ApiError(404, "not_found")
    history = for_model(await repo.load_messages(session, conv.id))
    await session.commit()  # 読み取りのトランザクションを閉じて接続を返す（ストリーミング中に握らない）
    candidate = with_new_user(history, body.content)
    try:
        fitted = await fit_history(candidate, counter, budget=hs.history_max_input_tokens, system=SYSTEM)
    except ContextTooLong:
        raise ApiError(422, "invalid_request", TOO_LONG_MESSAGE) from None
    request = ChatRequest(messages=fitted.messages, system=SYSTEM, max_tokens=get_settings().llm_max_tokens)
    return PreparedTurn(conv.id, body.content, request, fitted)


async def prime_turn(turn: Annotated[PreparedTurn, Depends(prepare_turn)], provider: ProviderDep,
                     ctx: ToolContextDep, limits: LimitsDep) -> PrimedLoop:
    """依存関数の中で先読みする。ここで ProviderError が出れば、例外ハンドラが JSON のエラー本文にする。"""
    return await prime_loop(provider, turn.request, ctx, limits=limits)


async def save_turn(factory: async_sessionmaker[AsyncSession], conversation_id: str,
                    rows: list[StoredMessage]) -> bool:
    """1往復を1つのトランザクションで保存する。ストリーミングの後なので、短い専用のセッションを開く。"""
    try:
        async with factory() as session:
            await repo.append_messages(session, conversation_id, rows)
            await session.commit()
    except SQLAlchemyError:
        logger.exception("save_turn_failed conversation_id=%s", conversation_id)
        return False
    return True


@app.post("/api/conversations/{conversation_id}/messages", response_class=EventSourceResponse)
async def post_message(request: Request, turn: Annotated[PreparedTurn, Depends(prepare_turn)],
                       primed: Annotated[PrimedLoop, Depends(prime_turn)],
                       factory: FactoryDep) -> AsyncIterator[ServerSentEvent]:
    # ここに来た時点で、上流は1回目の最初のイベントを返している（＝開始前の失敗は起きなかった）
    message_id = new_id()  # 往復の最後に保存する assistant の ID を先に決めて、start で知らせる
    outcome = TurnOutcome(request_id=request.state.request_id, message_id=message_id)
    recorder = TurnRecorder(message_id, turn.user_text)

    async def save(rows: list[StoredMessage]) -> bool:
        return await save_turn(factory, turn.conversation_id, rows)

    events = relay_turn(request, primed, recorder, outcome, save, on_close=request.app.state.outcomes.append)
    async with aclosing(events):
        async for ev in events:
            yield ev
