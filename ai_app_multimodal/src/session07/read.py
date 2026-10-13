"""レシートを LLM に読ませる（セッション7）。

入力の種類で content block を切り替え（画像 → image ブロック、PDF → document ブロック）、
出力はどちらも同じスキーマ（ReceiptRead）で受け取って Pydantic で再検証する。
再試行の方針はセッション4と同じ：形が崩れていたときだけ1回だけ再試行（MAX_ATTEMPTS = 2）、
max_tokens の打ち切りと上流のエラーは再試行しない。
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass

import anthropic
from pydantic import ValidationError

from kondate.llm import ChatRequest, LLMProvider, Usage
from kondate.settings import get_settings
from src.session07.models import RECEIPT_SCHEMA, ReceiptRead

log = logging.getLogger(__name__)

RECEIPT_PROMPT = "このレシートを読み取ってください。購入日はYYYY-MM-DDの形式、金額は円の整数で書いてください。"
MAX_ATTEMPTS = 2  # 1回目＋再試行1回


class UpstreamUnavailable(Exception):
    """LLM の API から応答を得られなかった（SDK の再試行も尽きた）。"""


class InvalidOutput(Exception):
    """応答はあったが、レシートの読み取り結果として使える形ではなかった。"""

    def __init__(self, reason: str, attempts: int, usage: Usage) -> None:
        super().__init__(reason)
        self.reason, self.attempts, self.usage = reason, attempts, usage


@dataclass(frozen=True)
class ReadResult:
    receipt: ReceiptRead
    attempts: int
    usage: Usage  # すべての試行の合計


def receipt_block(kind: str, data: bytes) -> dict:
    """画像なら image ブロック、PDF なら document ブロック。違うのはここだけ。"""
    b64 = base64.standard_b64encode(data).decode("ascii")
    if kind == "image":  # 受付で JPEG に作り直してあるので media_type は固定
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}
    if kind == "pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    raise ValueError(f"未対応の種類です: {kind}")


def build_request(kind: str, data: bytes, max_tokens: int | None = None) -> ChatRequest:
    return ChatRequest(
        messages=[{"role": "user", "content": [receipt_block(kind, data), {"type": "text", "text": RECEIPT_PROMPT}]}],
        output_schema=RECEIPT_SCHEMA,  # 画像でも PDF でも同じスキーマ
        max_tokens=max_tokens or get_settings().llm_max_tokens,
    )


def error_summary(e: ValidationError) -> list[str]:
    """どの項目がどの規則に違反したかだけを並べる。値（品名・金額＝購買の記録）はログに出さない。"""
    return [f"{'.'.join(str(p) for p in err['loc']) or '(全体)'}: {err['type']}" for err in e.errors()]


async def read_receipt(llm: LLMProvider, kind: str, data: bytes, max_tokens: int | None = None) -> ReadResult:
    req = build_request(kind, data, max_tokens)
    used_in = used_out = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = await llm.complete(req)
        except anthropic.APIError as e:
            raise UpstreamUnavailable() from e
        used_in += result.usage.input_tokens
        used_out += result.usage.output_tokens
        usage = Usage(used_in, used_out)
        if result.stop_reason == "max_tokens":
            log.warning("receipt: max_tokens で打ち切られました（%d回目）", attempt)
            raise InvalidOutput("max_tokens", attempt, usage)
        try:
            return ReadResult(ReceiptRead.model_validate_json(result.text), attempt, usage)
        except ValidationError as e:
            log.warning("receipt: 検証に失敗しました（%d回目）: %s", attempt, error_summary(e))
    raise InvalidOutput("validation", MAX_ATTEMPTS, usage)
