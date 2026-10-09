"""リトライ・サーキットブレーカ・フォールバックをまとめて、上流を「1回呼ぶ」部品にする。

経路（Route）を primary → light → openai の順に試す。各経路では
  ブレーカに聞く → 残り時間の中で呼ぶ → 結果をブレーカに記録する
を RetryPolicy の回数まで繰り返し、だめなら次の経路へ移る。締め切り（Deadline）は要求1つに1つ。
フォールバックしたら Served.fallback（経路名）を応答とログに残す（品質が落ちたことを隠さない）。
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from typing import Generic, TypeVar

import anyio
from redis.asyncio import Redis
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from kondate.clock import Clock

from .breaker import PREFIX, BreakerConfig, CircuitBreaker
from .providers import ChatRequest, ChatResult, LLMProvider, ProviderError
from .relay import Primed, prime
from .retry import Attempt, Deadline, Rand, RetryPolicy, Sleep, retry_call

logger = logging.getLogger("kondate.session11.fallback")

FALLBACK_HEADER = "x-kondate-fallback"
# 上流が壊れている兆候。ブレーカの失敗として数える（429 は「混んでいる」なので数えない。400 系はこちらの誤り）
BREAKER_KINDS = frozenset({"overloaded", "server_error", "timeout", "connection"})
# 別の経路なら通るかもしれない失敗。これ以外（bad_request・auth など）では次の経路へ移らない
FALLBACK_KINDS = BREAKER_KINDS | {"rate_limited", "breaker_open"}

T = TypeVar("T")
Call = Callable[[LLMProvider, ChatRequest], Awaitable[T]]


@dataclass(frozen=True)
class Route:
    name: str  # primary / light / openai（ブレーカのキーにもなる）
    provider: LLMProvider
    model: str | None = None  # None ならプロバイダの既定モデル
    policy: RetryPolicy = RetryPolicy(max_attempts=2)


@dataclass
class Served(Generic[T]):
    """上流から得た値と、どの経路で・何回目で得たか。"""

    value: T
    route: str
    attempts: list[Attempt]
    reason: str | None = None  # 前の経路を諦めた理由（最初の経路で答えたら None）

    @property
    def fallback(self) -> str | None:
        """フォールバックした経路名。最初の経路（primary）で答えたら None。"""
        return self.route if self.reason is not None else None


class ResilientLLM:
    def __init__(self, routes: Sequence[Route], *, redis: Redis, clock: Clock, deadline_seconds: float = 20.0,
                 breaker: BreakerConfig = BreakerConfig(), sleep: Sleep = asyncio.sleep,
                 rand: Rand = random.random, prefix: str = PREFIX) -> None:
        if not routes:
            raise ValueError("経路を1つ以上渡してください")
        self.routes = list(routes)
        self.clock = clock
        self.deadline_seconds = deadline_seconds
        self.sleep, self.rand = sleep, rand
        self.breakers = {r.name: CircuitBreaker(redis, r.name, breaker, prefix) for r in self.routes}

    async def complete(self, chat: ChatRequest) -> Served[ChatResult]:
        return await self.run(chat, lambda provider, req: provider.complete(req))

    async def prime(self, chat: ChatRequest) -> Served[Primed]:
        """ストリームの先読み（最初のイベント）までを再試行する。受け取ったあとは、もう再試行しない。"""
        return await self.run(chat, prime)

    async def _attempt(self, route: Route, chat: ChatRequest, call: Call[T], budget: float) -> T:
        breaker = self.breakers[route.name]
        if not (await breaker.allow(self.clock.now())).allowed:
            raise ProviderError("breaker_open", provider=route.provider.name)  # 上流を呼ばずに断る
        try:
            with anyio.fail_after(budget):  # 1回の試行に渡すのは、締め切りまでの残り時間だけ
                value = await call(route.provider, chat)
        except TimeoutError:
            await breaker.record_failure(self.clock.now())
            raise ProviderError("timeout", provider=route.provider.name) from None
        except ProviderError as e:
            if e.kind in BREAKER_KINDS:
                await breaker.record_failure(self.clock.now())
            raise
        await breaker.record_success(self.clock.now())
        return value

    async def run(self, chat: ChatRequest, call: Call[T]) -> Served[T]:
        """call(provider, chat) を、経路ごとにリトライしながら順に試す。"""
        deadline = Deadline(self.clock, self.deadline_seconds)
        attempts: list[Attempt] = []
        reason: str | None = None
        for i, route in enumerate(self.routes):
            routed = replace(chat, model=route.model) if route.model else chat
            try:
                value = await retry_call(
                    lambda budget, route=route, routed=routed: self._attempt(route, routed, call, budget),
                    policy=route.policy, deadline=deadline, sleep=self.sleep, rand=self.rand,
                    route=route.name, attempts=attempts)
            except ProviderError as e:
                last_route = i == len(self.routes) - 1
                if e.kind not in FALLBACK_KINDS or last_route or deadline.expired:
                    raise
                reason = e.kind
                logger.warning("route_failed route=%s kind=%s next=%s", route.name, e.kind, self.routes[i + 1].name)
                continue
            if reason is not None:
                logger.warning("fallback route=%s reason=%s attempts=%d", route.name, reason, len(attempts))
            return Served(value, route.name, attempts, reason)
        raise AssertionError("ここには来ない")


class FallbackHeaderMiddleware:
    """request.state.fallback に経路名があれば、応答ヘッダ x-kondate-fallback に載せる。

    SSE は本文を送り始めたらヘッダを変えられないので、ヘッダはここで一括して付ける。
    依存関数（先読み）は応答の開始より前に終わるので、JSON でも SSE でも同じ仕組みで足りる。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state = scope.setdefault("state", {})  # request.state と同じ辞書

        async def send_with_fallback(message: Message) -> None:
            if message["type"] == "http.response.start" and state.get("fallback"):
                MutableHeaders(scope=message)[FALLBACK_HEADER] = state["fallback"]
            await send(message)

        await self.app(scope, receive, send_with_fallback)
