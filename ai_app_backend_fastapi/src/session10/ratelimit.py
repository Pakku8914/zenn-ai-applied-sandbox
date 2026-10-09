"""レート制限とクォータを FastAPI につなぐ依存性と関数（S11・S13・final はこのファイルと limiter.py・plans.py をコピーする）。

1つの要求が通る順序：
  認証 → レート制限（RateLimitDep）→ 上流の待ち時間（check_upstream_cooldown）→ クォータの予約（reserve_tokens）
  → 上流 → 精算（settle）／失敗なら払い戻し（release_after_failure）
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


# ---------------------------------------------------------------- ヘッダ


def retry_after_header(wait_ms: int) -> str:
    """ミリ秒を retry-after の秒に切り上げる。0 は返さない（待たずに再送させないため）。"""
    return str(max(1, math.ceil(wait_ms / 1000)))


def request_headers(limits: PlanLimits, remaining: int) -> dict[str, str]:
    return {"x-ratelimit-limit-requests": str(limits.requests_per_minute),
            "x-ratelimit-remaining-requests": str(remaining)}


def token_headers(state: QuotaState) -> dict[str, str]:
    return {"x-ratelimit-limit-tokens": str(state.limit), "x-ratelimit-remaining-tokens": str(state.remaining)}


# ---------------------------------------------------------------- レート制限（依存性）


@dataclass(frozen=True)
class Admission:
    """レート制限を通った要求。ルートはここから利用者とプランの上限を受け取る。"""

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
    for name, value in headers.items():  # 通したときも残りの回数を知らせる
        response.headers[name] = value
    return Admission(user, limits, result.remaining)


RateLimitDep = Annotated[Admission, Depends(enforce_rate_limit)]


# ---------------------------------------------------------------- 上流の待ち時間と、クォータの予約・精算


async def check_upstream_cooldown(limiter: Limiter, now: datetime) -> None:
    """上流が 429 で「待って」と言った時間の間は、上流を呼ばずに 429 を返す（全利用者で共有）。"""
    wait_ms = await limiter.upstream_wait_ms(now)
    if wait_ms > 0:
        raise ApiError(429, "rate_limited", headers={"retry-after": retry_after_header(wait_ms)})


def reservation_amount(chat: ChatRequest) -> int:
    """予約する量＝入力の見積もり＋出力の上限（max_tokens）。出力は終わるまで分からないので、上限で押さえる。"""
    return estimate_input_tokens(chat) + chat.max_tokens


async def reserve_tokens(limiter: Limiter, admission: Admission, amount: int, now: datetime,
                         settings: LimitSettings) -> Reservation:
    result = await limiter.reserve(admission.user.id, admission.limits, amount, now, settings.hold_seconds)
    if result.reservation is None:
        raise ApiError(429, "quota_exceeded",
                       headers={**token_headers(result.state), "retry-after": str(seconds_until_reset(now))})
    return result.reservation


def usage_tokens(usage: Usage) -> int:
    """クォータに数えるトークン（入力・出力・キャッシュの読み書きをすべて足す）。"""
    return (usage.input_tokens + usage.output_tokens
            + usage.cache_read_input_tokens + usage.cache_creation_input_tokens)


async def settle(limiter: Limiter, reservation: Reservation, actual_tokens: int) -> int | None:
    """実際に使った量で精算する。キャンセルの最中でも最後までやり切るよう、シールドして待つ。"""
    with anyio.CancelScope(shield=True):
        return await limiter.settle(reservation, actual_tokens)


async def release_after_failure(limiter: Limiter, reservation: Reservation, exc: BaseException,
                                now: datetime) -> None:
    """上流から答えを受け取れなかった：予約を全額払い戻す。上流の 429 なら、待ち時間を全員で共有する。"""
    with anyio.CancelScope(shield=True):
        await limiter.settle(reservation, 0)
        if isinstance(exc, ProviderError) and exc.kind == "rate_limited":
            await limiter.note_upstream_429(exc.retry_after or DEFAULT_RETRY_AFTER, now)


# ---------------------------------------------------------------- GET /api/usage（API契約④）


async def usage_today(limiter: Limiter, user: CurrentUser, settings: LimitSettings, now: datetime) -> dict:
    """{plan, used_today, limit_today, requests_per_minute}。used_today は精算済みの量（予約中は含めない）。"""
    limits = settings.for_plan(user.plan)
    state = await limiter.quota_state(user.id, limits, now)
    return {"plan": user.plan, "used_today": state.used, "limit_today": limits.tokens_per_day,
            "requests_per_minute": limits.requests_per_minute}
