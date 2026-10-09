"""リトライ・サーキットブレーカ・フォールバックをまとめて、上流を「1回呼ぶ」部品にする。

session11/fallback.py から、この章で使う complete() の経路だけを写したもの
（ストリームの先読み prime() と、ヘッダを付ける FallbackHeaderMiddleware は省いた）。

経路（Route）を primary → light の順に試す。各経路では
  ブレーカに聞く → 残り時間の中で呼ぶ → 結果をブレーカに記録する
を RetryPolicy の回数まで繰り返し、だめなら次の経路へ移る。締め切り（Deadline）は要求1つに1つ。
フォールバックしたら Served.fallback（経路名）を残す（品質が落ちたことを隠さない）。
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

from kondate.clock import Clock

from .breaker import PREFIX, BreakerConfig, CircuitBreaker
from .providers import ChatRequest, ChatResult, LLMProvider, ProviderError
from .retry import Attempt, Deadline, Rand, RetryPolicy, Sleep, retry_call

logger = logging.getLogger("kondate.review03.fallback")

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
