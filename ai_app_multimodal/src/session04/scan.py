"""冷蔵庫の写真を LLM に読ませ、構造化出力を Pydantic で再検証する（セッション4）。

再試行の方針（本書で固定する値）：
- 検証に通らなかった（範囲外の値・欠けた項目など）ときだけ、同じ依頼を1回だけ再試行する（MAX_ATTEMPTS = 2）
- max_tokens で打ち切られたときは再試行しない（同じ上限なら同じところで切れる）
- 上流のエラー（429・5xx・接続失敗）はここで再試行しない（SDK が既定で2回再試行している）
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass

import anthropic
from pydantic import ValidationError

from kondate.llm import ChatRequest, LLMProvider, Usage
from kondate.settings import get_settings
from src.session04.models import FRIDGE_SCHEMA, FridgeScan

log = logging.getLogger(__name__)

FRIDGE_PROMPT = "冷蔵庫の写真に写っている食材をすべて挙げてください。分量が分からないものは見た目から推定してください。"
MAX_ATTEMPTS = 2  # 1回目＋再試行1回


class UpstreamUnavailable(Exception):
    """LLM の API から応答を得られなかった（SDK の再試行も尽きた）。"""


class InvalidOutput(Exception):
    """応答はあったが、食材リストとして使えなかった。"""

    def __init__(self, reason: str, attempts: int, usage: Usage) -> None:
        super().__init__(reason)
        self.reason, self.attempts, self.usage = reason, attempts, usage


@dataclass(frozen=True)
class ScanResult:
    scan: FridgeScan
    attempts: int
    usage: Usage  # すべての試行の合計（再試行したぶんも料金はかかる）


def build_request(jpeg: bytes, max_tokens: int | None = None) -> ChatRequest:
    image = {"type": "image", "source": {
        "type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(jpeg).decode("ascii"),
    }}
    return ChatRequest(
        messages=[{"role": "user", "content": [image, {"type": "text", "text": FRIDGE_PROMPT}]}],
        output_schema=FRIDGE_SCHEMA,
        max_tokens=max_tokens or get_settings().llm_max_tokens,
    )


def error_summary(e: ValidationError) -> list[str]:
    """どの項目がどの規則に違反したかだけを並べる。値そのもの（写真の中身）はログに出さない。"""
    return [f"{'.'.join(str(p) for p in err['loc']) or '(全体)'}: {err['type']}" for err in e.errors()]


async def scan_fridge(llm: LLMProvider, jpeg: bytes, max_tokens: int | None = None) -> ScanResult:
    req = build_request(jpeg, max_tokens)
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
            log.warning("fridge scan: max_tokens で打ち切られました（%d回目）", attempt)
            raise InvalidOutput("max_tokens", attempt, usage)
        try:
            return ScanResult(FridgeScan.model_validate_json(result.text), attempt, usage)
        except ValidationError as e:
            log.warning("fridge scan: 検証に失敗しました（%d回目）: %s", attempt, error_summary(e))
    raise InvalidOutput("validation", MAX_ATTEMPTS, usage)
