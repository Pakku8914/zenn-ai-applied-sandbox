"""問題3：クォータの予約・精算と、リトライ・フォールバックつきの呼び出しを1つにまとめる。

順序（session10 の ratelimit.py と同じ）：
  上流の待ち時間 → 予約（入力の見積もり＋max_tokens）→ ResilientLLM（リトライ・フォールバック）→ 精算／払い戻し
予約と精算は「呼び出し1つに1回」。何回リトライしても、どの経路で答えても、引くのは利用者のプランのクォータだけ。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from kondate.clock import Clock

from .fallback import ResilientLLM, Served
from .limiter import Limiter, QuotaState
from .plans import PlanLimits, seconds_until_reset
from .providers import ChatRequest, ChatResult, ProviderError
from .ratelimit import release_after_failure, reservation_amount, settle, usage_tokens


class QuotaExceeded(Exception):
    """その日のクォータに、この呼び出しの予約が入らない。JST の 0 時まで直らない。"""

    def __init__(self, state: QuotaState, retry_after: int) -> None:
        super().__init__("quota_exceeded")
        self.state = state
        self.retry_after = retry_after


@dataclass(frozen=True)
class Metered:
    served: Served[ChatResult]
    reserved: int  # 予約した量（入力の見積もり＋max_tokens）
    charged: int  # クォータに数えた量（実際に答えた経路の usage）
    used_today: int | None  # 精算後のその日の使用量（予約が期限切れで精算できなければ None）


async def metered_complete(llm: ResilientLLM, limiter: Limiter, user_id: str, limits: PlanLimits,
                           chat: ChatRequest, *, clock: Clock, hold_seconds: int) -> Metered:
    wait_ms = await limiter.upstream_wait_ms(clock.now())
    if wait_ms > 0:  # 上流が「待て」と言った時間の間は、予約も上流の呼び出しもしない（S10）
        raise ProviderError("rate_limited", provider="limiter", retry_after=max(1, math.ceil(wait_ms / 1000)))
    amount = reservation_amount(chat)
    now = clock.now()
    result = await limiter.reserve(user_id, limits, amount, now, hold_seconds)
    if result.reservation is None:
        raise QuotaExceeded(result.state, seconds_until_reset(now))
    try:
        served = await llm.complete(chat)  # リトライもフォールバックもこの中。予約は増やさない（S11）
    except BaseException as exc:
        await release_after_failure(limiter, result.reservation, exc, clock.now())  # 全額払い戻す
        raise
    charged = usage_tokens(served.value.usage)  # 答えた経路（light でも）の実際の usage
    used = await settle(limiter, result.reservation, charged)
    return Metered(served, amount, charged, used)
