"""レート制限（トークンバケット・Python 版）

時刻を callable で受け取ります。テストで実時間を待たないためです。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

DEFAULT_MAX_KEYS = 1000


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int = 0
    retry_after_ms: int = 0


class RateLimiter:
    def __init__(
        self,
        *,
        capacity: int,
        refill_per_second: float,
        now: Callable[[], int],
        max_keys: int = DEFAULT_MAX_KEYS,
    ) -> None:
        self._capacity = capacity
        self._refill = refill_per_second
        self._now = now
        self._max_keys = max_keys
        #: キー -> (残トークン, 最終更新時刻)
        self._buckets: dict[str, tuple[float, int]] = {}

    def size(self) -> int:
        return len(self._buckets)

    def try_consume(self, key: str, cost: int = 1) -> RateLimitDecision:
        at = self._now()
        current = self._buckets.get(key)
        if current is None and len(self._buckets) >= self._max_keys:
            oldest = min(self._buckets, key=lambda name: self._buckets[name][1])
            del self._buckets[oldest]

        tokens, updated_at = current if current is not None else (float(self._capacity), at)
        elapsed_ms = max(0, at - updated_at)
        tokens = min(float(self._capacity), tokens + (elapsed_ms / 1000) * self._refill)

        if tokens < cost:
            self._buckets[key] = (tokens, at)
            retry_after = math.ceil((cost - tokens) / self._refill * 1000)
            return RateLimitDecision(False, retry_after_ms=retry_after)

        self._buckets[key] = (tokens - cost, at)
        return RateLimitDecision(True, remaining=int(tokens - cost))
