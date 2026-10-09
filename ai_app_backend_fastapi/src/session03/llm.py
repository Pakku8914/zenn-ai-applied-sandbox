"""AsyncAnthropic の生成と、1回の呼び出し（usage と request_id をログに残す）。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import anthropic
from anthropic import AsyncAnthropic

from src.session03.config import LLMSettings
from src.session03.errors import translate

logger = logging.getLogger("kondate.session03.llm")


def setup_logging() -> None:
    """出力先を1つだけ付ける（構造化ログはセッション14で扱う）。"""
    log = logging.getLogger("kondate.session03")
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)


def make_timeout(settings: LLMSettings) -> anthropic.Timeout:
    # 第1引数が read・write・pool の値になり、connect だけ個別に短くする
    return anthropic.Timeout(settings.llm_timeout_seconds, connect=settings.llm_connect_timeout_seconds)


def make_client(settings: LLMSettings) -> AsyncAnthropic:
    return AsyncAnthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
        base_url=settings.anthropic_base_url,
        timeout=make_timeout(settings),
        max_retries=settings.llm_max_retries,
    )


@dataclass(frozen=True)
class Answer:
    text: str
    stop_reason: str | None
    usage: dict[str, int]
    upstream_request_id: str | None


async def ask_llm(llm: AsyncAnthropic, settings: LLMSettings, question: str, *,
                  request_id: str, extra_headers: dict[str, str] | None = None) -> Answer:
    try:
        message = await llm.messages.create(
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            messages=[{"role": "user", "content": question}],
            extra_headers=extra_headers or None,
        )
    except anthropic.APIError as exc:
        # 上流が応答を返していれば、その request-id をログに残す
        upstream = exc.response.headers.get("request-id") if isinstance(exc, anthropic.APIStatusError) else None
        logger.warning("llm_call failed request_id=%s upstream_request_id=%s error=%s status=%s",
                       request_id, upstream or "-", type(exc).__name__, getattr(exc, "status_code", "-"))
        raise translate(exc) from exc

    u = message.usage
    usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
             "cache_read_input_tokens": u.cache_read_input_tokens or 0,
             "cache_creation_input_tokens": u.cache_creation_input_tokens or 0}
    logger.info("llm_call ok request_id=%s upstream_request_id=%s input_tokens=%d output_tokens=%d stop_reason=%s",
                request_id, message._request_id, u.input_tokens, u.output_tokens, message.stop_reason)
    text = "".join(block.text for block in message.content if block.type == "text")
    return Answer(text, message.stop_reason, usage, message._request_id)
