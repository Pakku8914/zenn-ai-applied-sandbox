"""ストリーミングの精算。relay_chat の SSE をそのまま流し、終わり方（完了・失敗・切断）に関係なく最後に1回だけ精算する。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import aclosing

from fastapi import Request
from fastapi.sse import ServerSentEvent

from .limiter import Limiter, Reservation
from .ratelimit import settle, usage_tokens
from .relay import Primed, StreamOutcome, relay_chat


async def settled_events(request: Request, primed: Primed, outcome: StreamOutcome, limiter: Limiter,
                         reservation: Reservation) -> AsyncIterator[ServerSentEvent]:
    events = relay_chat(request, primed, outcome)
    try:
        async with aclosing(events):
            async for ev in events:
                yield ev
    finally:
        # ここに来る前に relay_chat の finally が outcome.usage を埋めている
        # 完了なら上流の usage、途中で終わったなら送った分からの見積もり（usage_source=estimated）
        actual = usage_tokens(outcome.usage) if outcome.usage is not None else 0
        await settle(limiter, reservation, actual)
