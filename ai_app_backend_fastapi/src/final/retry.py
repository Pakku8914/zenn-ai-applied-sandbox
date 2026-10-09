"""リトライの部品（session11/retry.py のコピー）：天井付きの指数バックオフ＋フルジッタ、retry-after の尊重、締め切り。"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import TypeVar

from kondate.clock import Clock, FixedClock

from .providers import ProviderError

T = TypeVar("T")
Sleep = Callable[[float], Awaitable[None]]
Rand = Callable[[], float]


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    multiplier: float = 2.0
    max_retry_after: float = 60.0


@dataclass(frozen=True)
class Attempt:
    route: str
    number: int
    outcome: str
    waited: float


class Deadline:
    def __init__(self, clock: Clock, seconds: float) -> None:
        self.clock = clock
        self.expires_at = clock.now() + timedelta(seconds=seconds)

    def remaining(self) -> float:
        return max(0.0, (self.expires_at - self.clock.now()).total_seconds())

    @property
    def expired(self) -> bool:
        return self.remaining() <= 0


class FakeSleep:
    """テスト用の sleep。実際には待たず、待った秒を記録して FixedClock を進める。"""

    def __init__(self, clock: FixedClock) -> None:
        self.clock = clock
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(round(seconds, 3))
        self.clock.advance(seconds)


def backoff_delay(retry_index: int, policy: RetryPolicy, rand: Rand) -> float:
    ceiling = min(policy.max_delay, policy.base_delay * policy.multiplier ** (retry_index - 1))
    return ceiling * rand()


def retry_delay(retry_index: int, error: ProviderError, policy: RetryPolicy, rand: Rand) -> float:
    delay = backoff_delay(retry_index, policy, rand)
    if error.retry_after is not None:
        delay = max(delay, float(error.retry_after))
    return delay


async def retry_call(fn: Callable[[float], Awaitable[T]], *, policy: RetryPolicy, deadline: Deadline,
                     sleep: Sleep = asyncio.sleep, rand: Rand = random.random, route: str = "primary",
                     attempts: list[Attempt] | None = None) -> T:
    log = attempts if attempts is not None else []
    waited = 0.0
    for number in range(1, policy.max_attempts + 1):
        budget = deadline.remaining()
        if budget <= 0:
            raise ProviderError("timeout", provider=route)
        try:
            result = await fn(budget)
        except ProviderError as e:
            log.append(Attempt(route, number, e.kind, waited))
            if not e.retryable or number == policy.max_attempts:
                raise
            delay = retry_delay(number, e, policy, rand)
            if delay > policy.max_retry_after or delay >= deadline.remaining():
                raise
            await sleep(delay)
            waited = delay
            continue
        log.append(Attempt(route, number, "ok", waited))
        return result
    raise AssertionError("ここには来ない")
