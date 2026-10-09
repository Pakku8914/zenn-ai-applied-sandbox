"""レート制限とクォータを FastAPI につなぐ依存性と関数（session10/ratelimit.py のコピー）。

この章だけの変更：GET /api/usage の集計は台帳（aggregate.usage_today）に移したので、Redis 版の usage_today は持たない。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

import anyio
from fastapi import Depends, Request, Response
from redis.asyncio import Redis

from .auth import ClockDep, CurrentUserDep
from .errors import DEFAULT_RETRY_AFTER, ApiError
from .keys import CurrentUser
from .limiter import Limiter, QuotaState, Reservation
from .plans import LimitSettings, PlanLimits, seconds_until_reset
from .providers import ChatRequest, ProviderError, Usage
from .relay import estimate_input_tokens


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


def get_limit_settings() -> LimitSettings:
    return LimitSettings()


def get_limiter(redis: Annotated[Redis, Depends(get_redis)]) -> Limiter:
    return Limiter(redis)


LimiterDep = Annotated[Limiter, Depends(get_limiter)]
LimitSettingsDep = Annotated[LimitSettings, Depends(get_limit_settings)]


def retry_after_header(wait_ms: int) -> str:
    return str(max(1, math.ceil(wait_ms / 1000)))


def request_headers(limits: PlanLimits, remaining: int) -> dict[str, str]:
    return {"x-ratelimit-limit-requests": str(limits.requests_per_minute),
            "x-ratelimit-remaining-requests": str(remaining)}


def token_headers(state: QuotaState) -> dict[str, str]:
    return {"x-ratelimit-limit-tokens": str(state.limit), "x-ratelimit-remaining-tokens": str(state.remaining)}


@dataclass(frozen=True)
class Admission:
    user: CurrentUser
    limits: PlanLimits
    remaining_requests: int


async def enforce_rate_limit(response: Response, user: CurrentUserDep, limiter: LimiterDep,
                             settings: LimitSettingsDep, clock: ClockDep) -> Admission:
    limits = settings.for_plan(user.plan)
    result = await limiter.take_request(user.id, limits, clock.now())
    headers = request_headers(limits, result.remaining)
    if not result.allowed:
        raise ApiError(429, "rate_limited",
                       headers={**headers, "retry-after": retry_after_header(result.retry_after_ms)})
    for name, value in headers.items():
        response.headers[name] = value
    return Admission(user, limits, result.remaining)


RateLimitDep = Annotated[Admission, Depends(enforce_rate_limit)]


async def check_upstream_cooldown(limiter: Limiter, now: datetime) -> None:
    wait_ms = await limiter.upstream_wait_ms(now)
    if wait_ms > 0:
        raise ApiError(429, "rate_limited", headers={"retry-after": retry_after_header(wait_ms)})


def reservation_amount(chat: ChatRequest) -> int:
    return estimate_input_tokens(chat) + chat.max_tokens


async def reserve_tokens(limiter: Limiter, admission: Admission, amount: int, now: datetime,
                         settings: LimitSettings) -> Reservation:
    result = await limiter.reserve(admission.user.id, admission.limits, amount, now, settings.hold_seconds)
    if result.reservation is None:
        raise ApiError(429, "quota_exceeded",
                       headers={**token_headers(result.state), "retry-after": str(seconds_until_reset(now))})
    return result.reservation


def usage_tokens(usage: Usage) -> int:
    """クォータに数えるトークン（入力・出力・キャッシュの読み書きをすべて足す）。台帳の集計も同じ数え方にする。"""
    return (usage.input_tokens + usage.output_tokens
            + usage.cache_read_input_tokens + usage.cache_creation_input_tokens)


async def settle(limiter: Limiter, reservation: Reservation, actual_tokens: int) -> int | None:
    with anyio.CancelScope(shield=True):
        return await limiter.settle(reservation, actual_tokens)


async def release_after_failure(limiter: Limiter, reservation: Reservation, exc: BaseException,
                                now: datetime) -> None:
    with anyio.CancelScope(shield=True):
        await limiter.settle(reservation, 0)
        if isinstance(exc, ProviderError) and exc.kind == "rate_limited":
            await limiter.note_upstream_429(exc.retry_after or DEFAULT_RETRY_AFTER, now)
