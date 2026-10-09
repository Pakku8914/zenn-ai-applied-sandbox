"""問題7の解答：リトライ込みの「全体の締め切り」を asyncio.timeout で別に掛ける。

SDK のタイムアウトは「1回の試行の、段階ごとの上限」なので、リトライとバックオフの待ちを足した総時間は縛れない。
"""

from __future__ import annotations

import asyncio
import logging

from anthropic import AsyncAnthropic

from src.session03.config import LLMSettings
from src.session03.errors import ApiError
from src.session03.llm import Answer, ask_llm

logger = logging.getLogger("kondate.session03.q7")


async def ask_with_deadline(llm: AsyncAnthropic, settings: LLMSettings, question: str, *,
                            request_id: str, deadline_s: float,
                            extra_headers: dict[str, str] | None = None) -> Answer:
    try:
        async with asyncio.timeout(deadline_s):
            return await ask_llm(llm, settings, question, request_id=request_id, extra_headers=extra_headers)
    except TimeoutError:
        # 締め切りで打ち切った。進行中の HTTP 要求はキャンセルされ、その接続はプールに戻らず捨てられる
        logger.warning("llm_call deadline_exceeded request_id=%s deadline_s=%s", request_id, deadline_s)
        raise ApiError(504, "upstream_timeout") from None
