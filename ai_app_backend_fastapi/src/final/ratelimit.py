"""レート制限とクォータを FastAPI につなぐ（session13/ratelimit.py のコピー）。

最終プロジェクトでの変更：レート制限の依存性が「検証済みの本文（PreparedDep）」に依存するようにした。
FastAPI は依存性を順に解決するので、本文が 422 のときに回数を1回ぶん消費してしまうのを防げる（chat.py 参照）。
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated

import anyio
from fastapi import Depends, Request
from redis.asyncio import Redis

from .errors import DEFAULT_RETRY_AFTER, ApiError
from .limiter import (Limiter, LimitSettings, PlanLimits, QuotaState, Reservation, ReserveResult,
                      seconds_until_reset)
from .providers import ProviderError, Usage


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


def get_limit_settings() -> LimitSettings:
    return LimitSettings()


def get_limiter(redis: Annotated[Redis, Depends(get_redis)]) -> Limiter:
    return Limiter(redis)


RedisDep = Annotated[Redis, Depends(get_redis)]
LimiterDep = Annotated[Limiter, Depends(get_limiter)]
LimitSettingsDep = Annotated[LimitSettings, Depends(get_limit_settings)]


def retry_after_header(wait_ms: int) -> str:
    return str(max(1, math.ceil(wait_ms / 1000)))


def request_headers(limits: PlanLimits, remaining: int) -> dict[str, str]:
    return {"x-ratelimit-limit-requests": str(limits.requests_per_minute),
            "x-ratelimit-remaining-requests": str(remaining)}


def token_headers(state: QuotaState) -> dict[str, str]:
    return {"x-ratelimit-limit-tokens": str(state.limit), "x-ratelimit-remaining-tokens": str(state.remaining)}


async def take_request(limiter: Limiter, user_id: str, limits: PlanLimits, now: datetime) -> dict[str, str]:
    """1回ぶんを数える。断るときは 429 rate_limited（retry-after と x-ratelimit-* 付き）。"""
    result = await limiter.take_request(user_id, limits, now)
    headers = request_headers(limits, result.remaining)
    if not result.allowed:
        raise ApiError(429, "rate_limited", headers={**headers, "retry-after": retry_after_header(result.retry_after_ms)})
    return headers


async def check_upstream_cooldown(limiter: Limiter, now: datetime) -> None:
    wait_ms = await limiter.upstream_wait_ms(now)
    if wait_ms > 0:
        raise ApiError(429, "rate_limited", headers={"retry-after": retry_after_header(wait_ms)})


async def reserve_tokens(limiter: Limiter, user_id: str, limits: PlanLimits, amount: int, now: datetime,
                         settings: LimitSettings) -> ReserveResult:
    result = await limiter.reserve(user_id, limits, amount, now, settings.hold_seconds)
    if result.reservation is None:
        raise ApiError(429, "quota_exceeded",
                       headers={**token_headers(result.state), "retry-after": str(seconds_until_reset(now))})
    return result


def usage_tokens(usage: Usage) -> int:
    """クォータに数えるトークン（入力・出力・キャッシュの読み書きをすべて足す）。台帳の集計も同じ数え方にする。"""
    return (usage.input_tokens + usage.output_tokens
            + usage.cache_read_input_tokens + usage.cache_creation_input_tokens)


async def settle(limiter: Limiter, reservation: Reservation, actual_tokens: int) -> int | None:
    """予約を実際の量で精算する。切断で止められている最中でもやり切る。"""
    with anyio.CancelScope(shield=True):
        return await limiter.settle(reservation, actual_tokens)


async def release_after_failure(limiter: Limiter, result: ReserveResult, exc: BaseException,
                                now: datetime) -> None:
    """上流が 200 で応じなかった：予約を全額払い戻す。上流の 429 なら、待ち時間を全台で共有する。"""
    assert result.reservation is not None
    with anyio.CancelScope(shield=True):
        await limiter.settle(result.reservation, 0)
        if isinstance(exc, ProviderError) and exc.kind == "rate_limited":
            await limiter.note_upstream_429(exc.retry_after or DEFAULT_RETRY_AFTER, now)
