"""練習問題4の解答：残りのクォータに合わせて max_tokens を縮めてから予約する。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .limiter import Limiter, QuotaState, Reservation
from .plans import PlanLimits
from .providers import ChatRequest
from .relay import estimate_input_tokens


class QuotaShort(Exception):
    """残りが少なすぎて、意味のある長さの答えを返せない。"""

    def __init__(self, state: QuotaState) -> None:
        super().__init__("quota_short")
        self.state = state


async def reserve_fitting(limiter: Limiter, user_id: str, limits: PlanLimits, chat: ChatRequest, now: datetime,
                          hold_seconds: int, *, min_output: int = 256) -> tuple[Reservation, ChatRequest]:
    input_tokens = estimate_input_tokens(chat)
    state = await limiter.quota_state(user_id, limits, now)
    room = state.remaining - input_tokens  # 出力に使える残り
    if room < min_output:
        raise QuotaShort(state)
    fitted = replace(chat, max_tokens=min(chat.max_tokens, room))
    # 読んでから予約するまでに別の要求が使ったかもしれない。判定は予約の Lua がもう一度原子的に行う
    result = await limiter.reserve(user_id, limits, input_tokens + fitted.max_tokens, now, hold_seconds)
    if result.reservation is None:
        raise QuotaShort(result.state)
    return result.reservation, fitted
