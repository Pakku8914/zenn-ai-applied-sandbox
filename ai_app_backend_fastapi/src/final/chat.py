"""POST /api/chat：AI SDK の DefaultChatTransport がそのまま読める UI Message Stream を返す。

開始前（依存関数。失敗は JSON のエラー本文）：
  admit_stream（停止中・満員なら 503）→ 認証（401）→ 本文の検証と変換（422）→ レート制限（429）
  → 予算（402）→ 上流の待ち時間（429）→ クォータの予約（429）→ 先読み（リトライ・フォールバック。503/504/502/429）
開始後（ChatTurn.stream。失敗は error チャンク → finish(error) → [DONE]）：
  start → ステップごとの start-step … finish-step → 保存 → 台帳 → data-usage → finish → [DONE]
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import deque
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from kondate.clock import Clock
from kondate.settings import get_settings

from . import repo
from .aggregate import used_today
from .auth import CurrentUserDep
from .breaker import BreakerConfig
from .budget import BudgetSettings, check_budget
from .deps import ClockDep, FactoryDep, SessionDep
from .errors import MESSAGES, ApiError, ServiceUnavailable, stream_error_type
from .fallback import ResilientLLM, Route
from .history import ContextTooLong, estimate_input_tokens, fit_messages
from .jobs import JobSettingsDep, StoreDep, enqueue_plan_week
from .keys import CurrentUser
from .lifecycle import Drain, StreamGate, pumped
from .limiter import Limiter, PlanLimits, ReserveResult
from .loop import (LoopDone, LoopEvent, PrimedLoop, StepDone, ToolLimits, ToolResult, add_usage, close_upstream,
                   prime_loop, with_first)
from .metering import UsageRecord, save_quietly
from .models import new_id
from .pricing import PriceTable, PriceTableDep
from .providers import ChatRequest, ProviderError, TextDelta, ToolCallDelta, ToolCallDone, ToolCallStart, Usage
from .ratelimit import (LimiterDep, LimitSettingsDep, RedisDep, check_upstream_cooldown, release_after_failure,
                        reserve_tokens, settle, take_request, token_headers, usage_tokens)
from .retry import Sleep
from .settings import SYSTEM_PROMPT, FinalSettings
from .tools import ToolContext, tool_definitions
from .turn import STEP_LIMIT_NOTE, StoredMessage, TurnRecorder
from .uimessages import TOO_LONG_MESSAGE, ChatIn, InvalidMessages, to_anthropic_messages
from .uistream import DONE_LINE, UI_STREAM_HEADERS, UiWriter, encode, finish_reason

logger = logging.getLogger("kondate.final.chat")
router = APIRouter()


class SaveFailed(Exception):
    """1往復の保存に失敗した（usage と finish は送らず、error internal_error で閉じる）。"""


# ---------------------------------------------------------------- 依存関数（すべてモジュール直下に置く）


def get_final_settings(request: Request) -> FinalSettings:
    return request.app.state.settings


def get_routes(request: Request) -> list[Route]:
    return request.app.state.routes


def get_sleep() -> Sleep:
    return asyncio.sleep


def get_model() -> str:
    return get_settings().llm_model


def get_tool_limits() -> ToolLimits:
    return ToolLimits()


def get_budget_settings() -> BudgetSettings:
    return BudgetSettings()


def get_drain(request: Request) -> Drain:
    return request.app.state.drain


def get_gate(request: Request) -> StreamGate:
    return request.app.state.gate


SettingsDep = Annotated[FinalSettings, Depends(get_final_settings)]
DrainDep = Annotated[Drain, Depends(get_drain)]
GateDep = Annotated[StreamGate, Depends(get_gate)]


def admit_stream(drain: DrainDep, gate: GateDep) -> None:
    """止まり始めた・満員なら、まだ 200 を返していないうちに 503 で断る（Session 16）。"""
    if drain.started or gate.full:
        raise ApiError(503, "service_unavailable", headers={"retry-after": "1"})


def forwarded_mock_headers(request: Request, settings: SettingsDep) -> dict[str, str]:
    """障害注入の x-mock-* だけを上流へ渡す。上流が mockllm のときだけ（本物の API には渡さない）。"""
    if not settings.upstream_is_mock:
        return {}
    return {k: v for k, v in request.headers.items() if k.startswith("x-mock-")}


def get_llm(routes: Annotated[list[Route], Depends(get_routes)], redis: RedisDep, clock: ClockDep,
            settings: SettingsDep, sleep: Annotated[Sleep, Depends(get_sleep)],
            mock: Annotated[dict[str, str], Depends(forwarded_mock_headers)]) -> ResilientLLM:
    if mock:
        routes = [r.with_headers(mock) for r in routes]
    breaker = BreakerConfig(failure_threshold=settings.breaker_failures, open_seconds=settings.breaker_open_seconds)
    return ResilientLLM(routes, redis=redis, clock=clock, deadline_seconds=settings.deadline_seconds,
                        breaker=breaker, sleep=sleep)


def get_tool_context(request: Request, user: CurrentUserDep, store: StoreDep, clock: ClockDep,
                     job_settings: JobSettingsDep) -> ToolContext:
    """ツールに渡す外の世界。plan_week は「認証した利用者」のジョブとして積む（LLM に利用者 ID を選ばせない）。"""
    request_id = request.state.request_id

    async def launch(days: int) -> dict:
        job = await enqueue_plan_week(store, user_id=user.id, days=days, clock=clock, settings=job_settings,
                                      request_id=request_id)
        return {"job_id": job.job_id, "status": job.status}

    return ToolContext(clock=clock, launch_plan_week=launch)


# ---------------------------------------------------------------- 開始前の関門


@dataclass(frozen=True)
class PreparedChat:
    chat_id: str
    title: str
    chat: ChatRequest  # 切り捨て済み・ツール定義つき
    user_content: list[dict]  # いま送られた user の発言（保存する1行目）
    keep_ids: list[str]  # クライアントの履歴に残っている assistant の ID（DB のずれの片付けに使う）
    input_estimate: int


async def prepare_chat(body: ChatIn, user: CurrentUserDep, session: SessionDep, settings: SettingsDep,
                       model: Annotated[str, Depends(get_model)]) -> PreparedChat:
    keep_ids = [m.id for m in body.messages[:-1] if m.role == "assistant"]
    partial = await repo.partial_ids(session, user.id, body.id, keep_ids)
    await session.commit()  # 読み取りのトランザクションを閉じる（ストリーミング中に接続を握らない）
    try:
        messages = to_anthropic_messages(body.messages, partial_ids=partial)
    except InvalidMessages as e:
        raise ApiError(422, "invalid_request", str(e)) from None
    chat = ChatRequest(messages=messages, system=SYSTEM_PROMPT, tools=tool_definitions(),
                       max_tokens=get_settings().llm_max_tokens, model=model)
    try:
        fitted = fit_messages(chat, settings.history_max_input_tokens)
    except ContextTooLong:
        raise ApiError(422, "invalid_request", TOO_LONG_MESSAGE) from None
    first_text = messages[0]["content"][0]["text"]
    return PreparedChat(body.id, first_text[:40], fitted, messages[-1]["content"], keep_ids,
                        estimate_input_tokens(fitted))


PreparedDep = Annotated[PreparedChat, Depends(prepare_chat)]


async def enforce_rate_limit(prepared: PreparedDep, user: CurrentUserDep, limiter: LimiterDep,
                             settings: LimitSettingsDep, clock: ClockDep, response: Response) -> PlanLimits:
    """prepared に依存させる：本文が 422 なら、ここ（回数の消費）まで来ない。"""
    limits = settings.for_plan(user.plan)
    for name, value in (await take_request(limiter, user.id, limits, clock.now())).items():
        response.headers[name] = value
    return limits


RateLimitDep = Annotated[PlanLimits, Depends(enforce_rate_limit)]


async def enforce_budget(prepared: PreparedDep, user: CurrentUserDep, limits: RateLimitDep, session: SessionDep,
                         settings: Annotated[BudgetSettings, Depends(get_budget_settings)], table: PriceTableDep,
                         clock: ClockDep) -> Decimal:
    """予約より前に置く：402 で断るときに、払い戻す予約が無くて済む（Session 13）。"""
    estimate = await check_budget(session, user, model=prepared.chat.model or "", input_estimate=prepared.input_estimate,
                                  max_tokens=prepared.chat.max_tokens, now=clock.now(), settings=settings, table=table)
    await session.commit()
    return estimate


BudgetDep = Annotated[Decimal, Depends(enforce_budget)]


@dataclass
class HeldTurn:
    """関門をすべて通り、予約を取り、上流の最初のイベントまで読めた往復。"""

    prepared: PreparedChat
    user: CurrentUser
    limits: PlanLimits
    reserved: ReserveResult
    primed: PrimedLoop
    route: str
    started_at: datetime


async def hold_turn(request: Request, response: Response, prepared: PreparedDep, user: CurrentUserDep,
                    limits: RateLimitDep, budget: BudgetDep, limiter: LimiterDep, limit_settings: LimitSettingsDep,
                    clock: ClockDep, llm: Annotated[ResilientLLM, Depends(get_llm)],
                    ctx: Annotated[ToolContext, Depends(get_tool_context)],
                    tool_limits: Annotated[ToolLimits, Depends(get_tool_limits)]) -> HeldTurn:
    now = clock.now()
    await check_upstream_cooldown(limiter, now)
    reserved = await reserve_tokens(limiter, user.id, limits, prepared.input_estimate + prepared.chat.max_tokens,
                                    now, limit_settings)
    try:
        # リトライとフォールバックは先読みまで（Session 11）。ここを過ぎたら 200 を返すので、もう再試行しない
        served = await llm.run(prepared.chat,
                               lambda provider, chat: prime_loop(provider, chat, ctx, limits=tool_limits))
    except BaseException as e:  # 上流が 200 で応じなかった：課金されないので台帳には書かず、予約を払い戻す
        await release_after_failure(limiter, reserved, e, clock.now())
        raise
    request.state.fallback = served.fallback  # x-kondate-fallback（FallbackHeaderMiddleware が付ける）
    for name, value in token_headers(reserved.state).items():
        response.headers[name] = value
    return HeldTurn(prepared, user, limits, reserved, served.value, served.route, now)


# ---------------------------------------------------------------- 開始後：ストリーム


@dataclass
class UsageTracker:
    """どこで終わっても usage を答えられるようにしておく。完走なら上流の値、途中なら見積もり。"""

    input_estimate: int
    steps: Usage = field(default_factory=lambda: Usage(0, 0))
    step_open: bool = True  # 先読みで1回目の呼び出しはもう始まっている
    step_bytes: int = 0
    final: Usage | None = None

    def feed(self, ev: LoopEvent) -> None:
        if isinstance(ev, (TextDelta, ToolCallStart, ToolCallDelta, ToolCallDone)):
            self.step_open = True
        if isinstance(ev, TextDelta):
            self.step_bytes += len(ev.text.encode("utf-8"))
        elif isinstance(ev, ToolCallDelta):
            self.step_bytes += len(ev.partial_json.encode("utf-8"))
        elif isinstance(ev, StepDone):
            self.steps = add_usage(self.steps, ev.usage)
            self.step_open, self.step_bytes = False, 0
        elif isinstance(ev, LoopDone):
            self.final = ev.usage

    def result(self) -> tuple[Usage, str]:
        if self.final is not None:
            return self.final, "upstream"
        extra = Usage(self.input_estimate if self.step_open else 0, math.ceil(self.step_bytes / 3))
        return add_usage(self.steps, extra), "estimated"


@dataclass
class TurnOutcome:
    """1往復の結末。ログと検証に使う（クライアントには送らない）。"""

    request_id: str
    message_id: str
    chat_id: str
    route: str
    reason: str | None = None  # completed / failed / cancelled / rejected
    error_type: str | None = None
    stop_reason: str | None = None
    saved: str | None = None  # complete / partial / failed
    tools: list[str] = field(default_factory=list)
    usage: Usage | None = None
    usage_source: str | None = None


@dataclass
class ChatTurn:
    held: HeldTurn
    outcome: TurnOutcome
    factory: async_sessionmaker[AsyncSession]
    table: PriceTable
    limiter: Limiter
    clock: Clock
    drain: Drain
    gate: StreamGate
    outcomes: deque
    recorder: TurnRecorder = field(init=False)
    save_attempted: bool = False

    def __post_init__(self) -> None:
        self.recorder = TurnRecorder(self.outcome.message_id, self.held.prepared.user_content)

    async def save(self, rows: list[StoredMessage], status: str) -> bool:
        self.save_attempted = True
        p = self.held.prepared
        with anyio.CancelScope(shield=True):  # 切断で止められている最中でも、保存は最後までやり切る
            ok = await repo.save_turn(self.factory, user_id=self.held.user.id, chat_id=p.chat_id, title=p.title,
                                      keep_ids=p.keep_ids, rows=rows)
        self.outcome.saved = status if ok else "failed"
        return ok

    async def record(self, tracker: UsageTracker) -> bool:
        usage, source = tracker.result()
        o = self.outcome
        o.usage, o.usage_source = usage, source
        record = UsageRecord(o.message_id, o.request_id, self.held.user.id, self.held.primed.chat.model or "",
                             self.held.started_at, usage, source, o.reason or "cancelled")
        return await save_quietly(self.factory, record, self.table)

    async def usage_data(self, usage: Usage) -> dict:
        async with self.factory() as session:
            used = await used_today(session, self.held.user.id, self.clock.now())
        return {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                "cache_read_input_tokens": usage.cache_read_input_tokens, "plan": self.held.user.plan,
                "used_today": used, "limit_today": self.held.limits.tokens_per_day}

    def metadata(self, usage: Usage) -> dict:
        return {"conversation_id": self.held.prepared.chat_id, "request_id": self.outcome.request_id,
                "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                          "cache_read_input_tokens": usage.cache_read_input_tokens,
                          "cache_creation_input_tokens": usage.cache_creation_input_tokens}}

    async def stream(self) -> AsyncIterator[bytes]:
        o = self.outcome
        writer = UiWriter()
        tracker = UsageTracker(self.held.prepared.input_estimate)
        entered = self.gate.try_enter()
        source = with_first(self.held.primed.first, self.held.primed.events)
        events = pumped(source, self.drain)
        recorded = False
        try:
            if not entered:  # 関所を同時にすり抜けた分。何も送っていないので、保存もしない
                self.save_attempted = True
                raise ServiceUnavailable("同時ストリームの上限")
            yield encode({"type": "start", "messageId": o.message_id})
            async for ev in events:
                tracker.feed(ev)
                self.recorder.feed(ev)
                if isinstance(ev, ToolResult):
                    o.tools.append(f"{ev.name}:{'error' if ev.is_error else 'ok'}")
                for chunk in writer.feed(ev):
                    yield encode(chunk)
                if not isinstance(ev, LoopDone):
                    continue
                o.stop_reason = ev.stop_reason
                if ev.stop_reason == "max_steps":
                    for chunk in writer.note(STEP_LIMIT_NOTE):  # 保存する締めの文を、同じ文でクライアントにも
                        yield encode(chunk)
                if not await self.save(self.recorder.completed(ev), "complete"):
                    raise SaveFailed()
                o.reason = "completed"
                recorded = await self.record(tracker)  # usage を送る前に台帳へ（used_today に今回の分が入る）
                yield encode({"type": "data-usage", "id": "usage", "data": await self.usage_data(ev.usage)})
                yield encode({"type": "finish", "finishReason": finish_reason(ev.stop_reason),
                              "messageMetadata": self.metadata(ev.usage)})
                yield DONE_LINE
                return
            raise ProviderError("bad_response", provider="loop")  # LoopDone の前にループが終わった
        except Exception as e:  # CancelledError（切断）は BaseException なので、ここには来ない
            if o.reason != "completed":
                o.reason = "failed" if entered else "rejected"
            o.error_type = stream_error_type(e)
            if isinstance(e, ProviderError):
                logger.warning("turn_failed", extra={"provider": e.provider, "kind": e.kind,
                                                     "upstream_request_id": e.request_id})
            elif not isinstance(e, ServiceUnavailable | SaveFailed):
                logger.exception("turn_failed")
            if not self.save_attempted:
                await self.save(self.recorder.interrupted(), "partial")  # 送ったところまでを残してから error
            yield encode({"type": "error", "errorText": MESSAGES[o.error_type]})  # 上流の生の文は出さない
            yield encode({"type": "finish", "finishReason": "error"})
            yield DONE_LINE
        finally:
            if entered:
                self.gate.leave()
            await close_upstream(events)
            await close_upstream(source)
            await close_upstream(self.held.primed.events)
            o.reason = o.reason or "cancelled"
            if not self.save_attempted:  # 切断・キャンセル：送る先は無いが、送ったところまでは残す
                await self.save(self.recorder.interrupted(), "partial")
            if not recorded:
                await self.record(tracker)
            await settle(self.limiter, self.held.reserved.reservation, usage_tokens(o.usage or Usage(0, 0)))
            logger.info("turn_closed", extra={
                "message_id": o.message_id, "chat_id": o.chat_id, "route": o.route, "reason": o.reason,
                "error_type": o.error_type, "stop_reason": o.stop_reason, "saved": o.saved,
                "tools": ",".join(o.tools), "usage_source": o.usage_source})
            self.outcomes.append(o)


@router.post("/api/chat", dependencies=[Depends(admit_stream)], response_model=None)
async def chat(request: Request, response: Response, held: Annotated[HeldTurn, Depends(hold_turn)],
               factory: FactoryDep, table: PriceTableDep, limiter: LimiterDep, clock: ClockDep, drain: DrainDep,
               gate: GateDep) -> StreamingResponse:
    # start の messageId ＝ 往復の最後に保存する assistant の ID ＝ 台帳の一意キー（turn_id）
    outcome = TurnOutcome(request_id=request.state.request_id, message_id=new_id(),
                          chat_id=held.prepared.chat_id, route=held.route)
    turn = ChatTurn(held, outcome, factory, table, limiter, clock, drain, gate, request.app.state.outcomes)
    # 依存関数が Response に積んだヘッダ（x-ratelimit-*）は、Response を直接返すと自動では移らないので写す
    limit_headers: Mapping[str, str] = {k: v for k, v in response.headers.items() if k.startswith("x-ratelimit-")}
    return StreamingResponse(turn.stream(), headers={**UI_STREAM_HEADERS, **limit_headers})


@router.get("/api/chat/{chat_id}/stream", status_code=204, response_model=None)
async def resume_stream(chat_id: str) -> Response:
    """AI SDK の再接続（resume）への応答。ストリームの再開はしないので、常に 204（＝再開するものは無い）。"""
    return Response(status_code=204)
