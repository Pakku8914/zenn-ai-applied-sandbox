"""問題5の解答：再試行のたびに上流の request-id は変わる。全部を1つの request_id に結び付けて残す。

- 1回の試行ごとに llm_attempt（attempt・outcome・upstream_status・upstream_request_id）
- 最後にまとめの llm_call（outcome・attempts・upstream_request_ids）
待ち時間の設計（指数バックオフ・ジッタ・デッドライン）は Session 11 で扱ったので、ここでは sleep を注入するだけにする。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import anthropic
from anthropic import AsyncAnthropic

from .llm import LLMConfig

logger = logging.getLogger("kondate.session14.q5")


async def ask_with_attempts(llm: AsyncAnthropic, cfg: LLMConfig, prompt: str, *, max_attempts: int = 3,
                            extra_headers: dict[str, str] | None = None,
                            sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> tuple[str, list[str]]:
    upstream_ids: list[str] = []
    for attempt in range(1, max_attempts + 1):
        try:
            message = await llm.messages.create(
                model=cfg.llm_model, max_tokens=cfg.llm_max_tokens,
                messages=[{"role": "user", "content": prompt}], extra_headers=extra_headers or None)
        except anthropic.APIStatusError as exc:
            uid = exc.response.headers.get("request-id")
            if uid:
                upstream_ids.append(uid)
            logger.warning("llm_attempt", extra={"attempt": attempt, "outcome": "error",
                                                 "upstream_status": exc.status_code, "upstream_request_id": uid})
            if exc.status_code < 500 or attempt == max_attempts:  # 4xx はやり直しても同じ
                logger.warning("llm_call", extra={"outcome": "error", "attempts": attempt,
                                                  "upstream_request_ids": upstream_ids})
                raise
            await sleep(0.1 * attempt)
            continue
        upstream_ids.append(message._request_id)
        logger.info("llm_attempt", extra={"attempt": attempt, "outcome": "ok",
                                          "upstream_request_id": message._request_id})
        logger.info("llm_call", extra={"outcome": "ok", "attempts": attempt, "upstream_request_ids": upstream_ids})
        return "".join(b.text for b in message.content if b.type == "text"), upstream_ids
    raise AssertionError("max_attempts は1以上にしてください")
