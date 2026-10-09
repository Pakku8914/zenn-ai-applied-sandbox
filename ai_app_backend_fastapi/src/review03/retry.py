"""リトライの部品：天井付きの指数バックオフ＋フルジッタ、retry-after の尊重、全体の締め切り（session11/retry.py のコピー）。

- 待つ関数（sleep）と乱数（rand）は注入する。テストでは FakeSleep が FixedClock を進めるので、実際には待たない
- 締め切りは Clock で測る。待っても締め切りに間に合わないときは、待たずに諦める
- SDK の自動リトライ（max_retries）は 0 にして、この層だけで再試行する（二重にしない）
"""

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
    max_attempts: int = 3  # 最初の1回を含む試行の回数
    base_delay: float = 0.5  # 1回目の再試行の前に待つ秒の上限（SDK の INITIAL_RETRY_DELAY と同じ）
    max_delay: float = 8.0  # 待ち時間の天井（SDK の MAX_RETRY_DELAY と同じ）
    multiplier: float = 2.0
    max_retry_after: float = 60.0  # これより長い retry-after は待たずに諦める


@dataclass(frozen=True)
class Attempt:
    """1回の試行の記録。ログと検証に使う。"""

    route: str  # primary / light / openai
    number: int  # その経路での何回目か（1 始まり）
    outcome: str  # ok か、失敗の kind（overloaded・breaker_open など）
    waited: float  # この試行の前に待った秒


class Deadline:
    """要求1つに許す全体の時間。リトライもフォールバックも、この残り時間の中で行う。"""

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
    """retry_index 回目（1 始まり）の再試行の前に待つ秒。天井付きの指数に 0〜1 倍を掛ける（フルジッタ）。"""
    ceiling = min(policy.max_delay, policy.base_delay * policy.multiplier ** (retry_index - 1))
    return ceiling * rand()


def retry_delay(retry_index: int, error: ProviderError, policy: RetryPolicy, rand: Rand) -> float:
    """retry-after があれば、それより早くは送らない（上流が「この秒数は待て」と言っている）。"""
    delay = backoff_delay(retry_index, policy, rand)
    if error.retry_after is not None:
        delay = max(delay, float(error.retry_after))
    return delay


async def retry_call(fn: Callable[[float], Awaitable[T]], *, policy: RetryPolicy, deadline: Deadline,
                     sleep: Sleep = asyncio.sleep, rand: Rand = random.random, route: str = "primary",
                     attempts: list[Attempt] | None = None) -> T:
    """fn(残り秒) を、再試行してよい失敗のあいだ繰り返す。最後の失敗は ProviderError のまま上へ流す。"""
    log = attempts if attempts is not None else []
    waited = 0.0
    for number in range(1, policy.max_attempts + 1):
        budget = deadline.remaining()
        if budget <= 0:  # 前の経路が締め切りを使い切った
            raise ProviderError("timeout", provider=route)
        try:
            result = await fn(budget)
        except ProviderError as e:
            log.append(Attempt(route, number, e.kind, waited))
            if not e.retryable or number == policy.max_attempts:
                raise
            delay = retry_delay(number, e, policy, rand)
            if delay > policy.max_retry_after or delay >= deadline.remaining():
                raise  # 待っても締め切りに間に合わない：待たずに諦める
            await sleep(delay)
            waited = delay
            continue
        log.append(Attempt(route, number, "ok", waited))
        return result
    raise AssertionError("ここには来ない")
