"""復習2で組み立てるアプリ（問題6）：会話の1往復で、ツール呼び出しループをストリーミングし、終わったら保存する。

起動：APP_MODULE=src.review02.app:app docker compose up -d --wait api
事前に：docker compose exec api python src/review02/setup_db.py

- POST /api/conversations                         … 会話を作る
- GET  /api/conversations/{conversation_id}       … 会話と保存した発言を返す（履歴の正）
- POST /api/conversations/{conversation_id}/messages … 1往復。先読み → SSE（id 付き）→ 保存 → usage → done
- GET  /api/chat/stream/{message_id}              … Last-Event-ID より後ろを Redis から再送する（できなければ 204）
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import AsyncIterator, Mapping
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from kondate.cache import make_redis
from kondate.clock import SystemClock
from kondate.db import engine
from kondate.settings import get_settings

from . import repo
from .deps import FactoryDep, SessionDep
from .errors import ApiError, install_error_handlers
from .loop import ToolLimits
from .models import new_id
from .providers import ChatRequest, LLMProvider, open_provider
from .relay import PrimedLoop, TurnOutcome, prime_loop, relay_turn
from .resume import EventLog, format_entries, load_replay, parse_last_event_id
from .tools import TOOLS, Tool, ToolContext

logger = logging.getLogger("kondate.review02")

SYSTEM = "あなたは献立相談AI「こんだてAI」です。レシピの情報は必ずツールで調べ、推測で答えないでください。"
CONVERSATION_NOT_FOUND = "指定された会話は存在しません"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    redis = make_redis()
    try:
        # 接続先とキーは ANTHROPIC_BASE_URL・ANTHROPIC_API_KEY から読む。再試行は再試行のセッションで扱う
        async with open_provider("anthropic", model=get_settings().llm_model, timeout=30.0,
                                 max_retries=0) as provider:
            app.state.provider, app.state.redis = provider, redis
            yield
    finally:
        await redis.aclose()
        await engine.dispose()


app = FastAPI(title="こんだてAI（復習2：ストリーミング × ツール × 保存）", lifespan=lifespan)
app.state.outcomes = deque(maxlen=100)  # 直近の往復の結末（検証で見る）
app.state.tool_context = ToolContext(clock=SystemClock())
app.state.tools = TOOLS
app.state.limits = ToolLimits()
install_error_handlers(app)


# ---------------------------------------------------------------- 依存関数（モジュール直下に置く）


def get_provider(request: Request) -> LLMProvider:
    return request.app.state.provider


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


def get_tool_context(request: Request) -> ToolContext:
    return request.app.state.tool_context


def get_tools(request: Request) -> Mapping[str, Tool]:
    return request.app.state.tools


def get_limits(request: Request) -> ToolLimits:
    return request.app.state.limits


ProviderDep = Annotated[LLMProvider, Depends(get_provider)]
RedisDep = Annotated[Redis, Depends(get_redis)]
ContextDep = Annotated[ToolContext, Depends(get_tool_context)]
ToolsDep = Annotated[Mapping[str, Tool], Depends(get_tools)]
LimitsDep = Annotated[ToolLimits, Depends(get_limits)]


# ---------------------------------------------------------------- 入出力のモデル


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


# ---------------------------------------------------------------- ルート


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
        raise ApiError(404, "not_found", CONVERSATION_NOT_FOUND)
    rows = await repo.load_messages(session, conv.id)
    return ConversationDetail(id=conv.id, user_id=conv.user_id, title=conv.title, messages=[
        MessageOut(id=r.id, seq=r.seq, role=r.role, content=r.content, status=r.status) for r in rows])


@dataclass(frozen=True)
class PreparedTurn:
    conversation_id: str
    user_content: list[dict]
    primed: PrimedLoop


async def prepare_turn(conversation_id: UUID, body: MessageIn, session: SessionDep, provider: ProviderDep,
                       ctx: ContextDep, tools: ToolsDep, limits: LimitsDep) -> PreparedTurn:
    """ストリームを始める前の仕事。ここで失敗すれば、共通エラー本文（JSON）で返せる。"""
    conv = await repo.get_conversation(session, str(conversation_id))
    if conv is None:
        raise ApiError(404, "not_found", CONVERSATION_NOT_FOUND)  # LLM を呼ぶ前に止める
    history = repo.to_api_messages(await repo.load_messages(session, conv.id))
    await session.commit()  # 読み取りのトランザクションを閉じて接続を返す（ストリーミング中に握らない）
    user_content = [{"type": "text", "text": body.content}]
    chat = ChatRequest(messages=[*history, {"role": "user", "content": user_content}], system=SYSTEM,
                       max_tokens=get_settings().llm_max_tokens)
    primed = await prime_loop(provider, chat, ctx, tools=tools, limits=limits)  # 最後に置く（問題5）
    return PreparedTurn(conv.id, user_content, primed)


async def save_turn(factory: async_sessionmaker[AsyncSession], turn: PreparedTurn, final_id: str,
                    added: list[dict]) -> bool:
    """1往復（user ＋ ループで増えた発言）を1つのトランザクションで保存する。短い専用のセッションを開く。"""
    try:
        async with factory() as session:
            await repo.append_messages(session, turn.conversation_id,
                                       [{"role": "user", "content": turn.user_content}, *added], final_id=final_id)
            await session.commit()
    except SQLAlchemyError:
        logger.exception("save_turn_failed conversation_id=%s", turn.conversation_id)
        return False
    return True


@app.post("/api/conversations/{conversation_id}/messages", response_class=EventSourceResponse)
async def post_message(request: Request, turn: Annotated[PreparedTurn, Depends(prepare_turn)],
                       factory: FactoryDep, redis: RedisDep) -> AsyncIterator[ServerSentEvent]:
    # ここに来た時点で、1回目の LLM 呼び出しは最初のイベントを返している（＝開始前の失敗は起きなかった）
    outcome = TurnOutcome(request_id=request.state.request_id, message_id=new_id())
    log = EventLog(redis, outcome.message_id)

    async def save(added: list[dict]) -> bool:
        return await save_turn(factory, turn, outcome.message_id, added)

    events = relay_turn(request, turn.primed, outcome, save, on_close=request.app.state.outcomes.append)
    async with aclosing(events):
        async for ev in events:
            yield await log.append(ev)  # id を付け、Redis に書いてから送る


@app.get("/api/chat/stream/{message_id}")
async def resume_stream(message_id: UUID, redis: RedisDep,
                        last_event_id: Annotated[str | None, Header()] = None) -> Response:
    try:
        after = parse_last_event_id(last_event_id)
    except ValueError:
        raise ApiError(422, "invalid_request", "Last-Event-ID の形式が正しくありません") from None
    entries = await load_replay(redis, str(message_id), after)
    if entries is None:
        return Response(status_code=204)  # 再送できるものが無い（知らない ID・期限切れ・途中で終わった）
    return Response(format_entries(entries), media_type="text/event-stream",
                    headers={"cache-control": "no-cache", "x-accel-buffering": "no"})
