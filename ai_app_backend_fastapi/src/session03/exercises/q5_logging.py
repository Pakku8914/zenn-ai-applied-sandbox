"""問題5の解答：成功・失敗のどちらでも、調査に要る項目だけを key=value の1行で残す。

残す：request_id・upstream_request_id・model・usage・stop_reason・error・status・question_chars
残さない：質問の本文（個人情報が入りうる）・API キー・上流のエラー文
"""

from __future__ import annotations

import json
import logging

import anthropic
from anthropic import AsyncAnthropic

from src.session03.config import LLMSettings
from src.session03.errors import translate
from src.session03.llm import Answer

logger = logging.getLogger("kondate.session03.q5")


def kv(**fields: object) -> str:
    """key=value を空白区切りで並べる。値に空白・=・" を含むときは JSON の文字列として引用する。"""
    parts = []
    for key, value in fields.items():
        text = "-" if value is None else str(value)
        if any(c in text for c in ' ="\n'):
            text = json.dumps(text, ensure_ascii=False)
        parts.append(f"{key}={text}")
    return " ".join(parts)


async def ask_logged(llm: AsyncAnthropic, settings: LLMSettings, question: str, *,
                     request_id: str, extra_headers: dict[str, str] | None = None) -> Answer:
    base = {"event": "llm_call", "request_id": request_id, "model": settings.llm_model,
            "question_chars": len(question)}
    try:
        message = await llm.messages.create(
            model=settings.llm_model, max_tokens=settings.llm_max_tokens,
            messages=[{"role": "user", "content": question}], extra_headers=extra_headers or None,
        )
    except anthropic.APIError as exc:
        status = exc.status_code if isinstance(exc, anthropic.APIStatusError) else None
        upstream = exc.response.headers.get("request-id") if isinstance(exc, anthropic.APIStatusError) else None
        logger.warning(kv(**base, outcome="error", error=type(exc).__name__, status=status,
                          upstream_request_id=upstream))
        raise translate(exc) from exc

    u = message.usage
    usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
             "cache_read_input_tokens": u.cache_read_input_tokens or 0,
             "cache_creation_input_tokens": u.cache_creation_input_tokens or 0}
    logger.info(kv(**base, outcome="ok", upstream_request_id=message._request_id,
                   stop_reason=message.stop_reason, input_tokens=u.input_tokens, output_tokens=u.output_tokens))
    text = "".join(b.text for b in message.content if b.type == "text")
    return Answer(text=text, stop_reason=message.stop_reason, usage=usage, upstream_request_id=message._request_id)
