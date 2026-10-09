"""リトライ・サーキットブレーカ・フォールバックで、上流を「1回呼ぶ」部品（session11/fallback.py のコピー）。

最終プロジェクトでは、ツールループの先読み（prime_loop）だけをこの部品に通す。先読みが成功したら、
ストリームはもう 200 で始まっているので、2ステップ目以降の失敗は再試行しない（同じ文が2回届いてしまう）。
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Generic, TypeVar

import anyio
from redis.asyncio import Redis
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from kondate.clock import Clock

from .breaker import PREFIX, BreakerConfig, CircuitBreaker
from .providers import ChatRequest, LLMProvider, ProviderError
from .retry import Attempt, Deadline, Rand, RetryPolicy, Sleep, retry_call

logger = logging.getLogger("kondate.final.fallback")

FALLBACK_HEADER = "x-kondate-fallback"
BREAKER_KINDS = frozenset({"overloaded", "server_error", "timeout", "connection"})
FALLBACK_KINDS = BREAKER_KINDS | {"rate_limited", "breaker_open"}

T = TypeVar("T")
Call = Callable[[LLMProvider, ChatRequest], Awaitable[T]]


@dataclass(frozen=True)
class Route:
    name: str  # primary / light（ブレーカのキーにもなる）
    provider: LLMProvider
    model: str | None = None
    policy: RetryPolicy = RetryPolicy(max_attempts=2)

    def with_headers(self, headers: Mapping[str, str]) -> Route:
        return replace(self, provider=self.provider.with_headers(headers))


@dataclass
class Served(Generic[T]):
    value: T
    route: str
    attempts: list[Attempt]
    reason: str | None = None

    @property
    def fallback(self) -> str | None:
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

    async def _attempt(self, route: Route, chat: ChatRequest, call: Call[T], budget: float) -> T:
        breaker = self.breakers[route.name]
        if not (await breaker.allow(self.clock.now())).allowed:
            raise ProviderError("breaker_open", provider=route.provider.name)
        try:
            with anyio.fail_after(budget):
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
                logger.warning("route_failed", extra={"route": route.name, "kind": e.kind,
                                                      "next": self.routes[i + 1].name})
                continue
            if reason is not None:
                logger.warning("fallback", extra={"route": route.name, "reason": reason, "attempts": len(attempts)})
            return Served(value, route.name, attempts, reason)
        raise AssertionError("ここには来ない")


class FallbackHeaderMiddleware:
    """request.state.fallback に経路名があれば、応答ヘッダ x-kondate-fallback に載せる（primary なら付けない）。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state = scope.setdefault("state", {})

        async def send_with_fallback(message: Message) -> None:
            if message["type"] == "http.response.start" and state.get("fallback"):
                MutableHeaders(scope=message)[FALLBACK_HEADER] = state["fallback"]
            await send(message)

        await self.app(scope, receive, send_with_fallback)
