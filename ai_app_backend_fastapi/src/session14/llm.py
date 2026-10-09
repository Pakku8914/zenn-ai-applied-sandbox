"""上流（mockllm／Claude API）の呼び出しと、そのログ（session03/llm.py を構造化ログ向けに手直ししたコピー）。

1回の呼び出しにつき1行、event="llm_call" を出す。成功は INFO、失敗・中断は WARNING。
- 残すもの：model・mode・prompt_chars・outcome・上流の request-id・上流のステータス・usage・stop_reason・所要時間
- 既定で残さないもの：プロンプト本文と応答本文。S14_LOG_PROMPTS=true のときだけ、伏せてから先頭だけ残す
request_id はここでは渡さない。ミドルウェア（または Celery のシグナル）が入れた contextvars から、フォーマッタが付ける。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import anthropic
from anthropic import AsyncAnthropic
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .mask import mask_text

if TYPE_CHECKING:
    from anthropic import AsyncStream
    from anthropic.types import RawMessageStreamEvent

logger = logging.getLogger("kondate.session14.llm")


class LLMConfig(BaseSettings):
    # 環境変数名はフィールド名を大文字にしたもの（anthropic_api_key → ANTHROPIC_API_KEY）
    model_config = SettingsConfigDict(extra="ignore")

    anthropic_api_key: SecretStr
    anthropic_base_url: str = "https://api.anthropic.com"
    llm_model: str  # compose.yaml か .env の LLM_MODEL で渡す
    llm_max_tokens: int = Field(default=1024, gt=0)
    llm_timeout_seconds: float = Field(default=30.0, gt=0)

    @property
    def forwards_mock_headers(self) -> bool:
        """障害注入ヘッダ（x-mock-*）を上流へ渡してよいか。接続先が mockllm のときだけ True。"""
        return urlsplit(self.anthropic_base_url).hostname == "mockllm"


class LogSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="S14_", extra="ignore")

    log_prompts: bool = False  # プロンプト本文をログに残すか。既定は残さない
    prompt_preview_chars: int = Field(default=80, ge=1, le=500)


def make_client(cfg: LLMConfig) -> AsyncAnthropic:
    return AsyncAnthropic(api_key=cfg.anthropic_api_key.get_secret_value(), base_url=cfg.anthropic_base_url,
                          timeout=anthropic.Timeout(cfg.llm_timeout_seconds, connect=5.0),
                          max_retries=0)  # リトライは Session 11 の retry_call に集約する


def prompt_fields(text: str, log: LogSettings) -> dict[str, object]:
    fields: dict[str, object] = {"prompt_chars": len(text)}
    if log.log_prompts:
        fields["prompt"] = mask_text(text)[: log.prompt_preview_chars]  # 先に伏せてから切る（逆だと伏せ損なう）
    return fields


def upstream_failure(exc: anthropic.APIError) -> dict[str, object]:
    """失敗の記録。上流が応答を返していれば、ステータスと request-id がある。"""
    if isinstance(exc, anthropic.APIStatusError):
        return {"upstream_status": exc.status_code, "upstream_request_id": exc.response.headers.get("request-id")}
    return {"upstream_status": None, "upstream_request_id": None}  # 接続失敗・時間切れには応答がない


def log_call(fields: Mapping[str, object], outcome: str, started: float, **more: object) -> None:
    """1回の上流呼び出しを1行にする。outcome は ok / error / cancelled。"""
    level = logging.INFO if outcome == "ok" else logging.WARNING
    logger.log(level, "llm_call", extra={**fields, "outcome": outcome, **more,
                                         "duration_ms": round((time.perf_counter() - started) * 1000, 1)})


@dataclass(frozen=True)
class Answer:
    text: str
    stop_reason: str | None
    input_tokens: int
    output_tokens: int


async def ask(llm: AsyncAnthropic, cfg: LLMConfig, log: LogSettings, prompt: str, *,
              extra_headers: dict[str, str] | None = None) -> Answer:
    fields = {"model": cfg.llm_model, "mode": "complete", **prompt_fields(prompt, log)}
    started = time.perf_counter()
    try:
        message = await llm.messages.create(
            model=cfg.llm_model, max_tokens=cfg.llm_max_tokens,
            messages=[{"role": "user", "content": prompt}], extra_headers=extra_headers or None)
    except anthropic.APIError as exc:
        log_call(fields, "error", started, **upstream_failure(exc), error=type(exc).__name__)
        raise
    u = message.usage
    log_call(fields, "ok", started, upstream_request_id=message._request_id, stop_reason=message.stop_reason,
             input_tokens=u.input_tokens, output_tokens=u.output_tokens)
    text = "".join(block.text for block in message.content if block.type == "text")
    return Answer(text, message.stop_reason, u.input_tokens, u.output_tokens)


@dataclass
class OpenedStream:
    """応答の始まり（HTTP のステータスとヘッダ）まで受け取った上流のストリーム。"""

    stream: AsyncStream[RawMessageStreamEvent]
    fields: dict[str, object]  # llm_call の行に載せる項目（上流の request-id を含む）
    started: float


async def open_stream(llm: AsyncAnthropic, cfg: LLMConfig, log: LogSettings, prompt: str, *,
                      extra_headers: dict[str, str] | None = None) -> OpenedStream:
    """ストリームを開く。開始前の 429・5xx はここで APIStatusError になる（JSON のエラー本文で返せる）。"""
    fields: dict[str, object] = {"model": cfg.llm_model, "mode": "stream", **prompt_fields(prompt, log)}
    started = time.perf_counter()
    try:
        stream = await llm.messages.create(
            model=cfg.llm_model, max_tokens=cfg.llm_max_tokens,
            messages=[{"role": "user", "content": prompt}], stream=True, extra_headers=extra_headers or None)
    except anthropic.APIError as exc:
        log_call(fields, "error", started, **upstream_failure(exc), error=type(exc).__name__)
        raise
    fields["upstream_request_id"] = stream.response.headers.get("request-id")  # 応答ヘッダは開いた時点で読める
    return OpenedStream(stream, fields, started)
