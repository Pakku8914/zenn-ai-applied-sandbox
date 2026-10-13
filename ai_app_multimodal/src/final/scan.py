"""冷蔵庫の写真を LLM に読ませる（セッション4の scan.py を、セッション14の書き方にそろえたもの）。

再試行の方針はセッション4と同じ：形が崩れていたときだけ1回だけ再試行（MAX_ATTEMPTS = 2）、
max_tokens の打ち切りは再試行しない、上流のエラー（anthropic.APIError）はそのまま上げる。
使ったトークンは試行ごとに used に足す（失敗した試行の分も料金はかかるので、呼び出し側が利用量に記録する）。
"""

from __future__ import annotations

import base64

from pydantic import ValidationError

from kondate.llm import ChatRequest, LLMProvider, Usage
from kondate.settings import get_settings
from src.final.models import FRIDGE_SCHEMA, FridgeScan

FRIDGE_PROMPT = "冷蔵庫の写真に写っている食材をすべて挙げてください。分量が分からないものは見た目から推定してください。"
MAX_ATTEMPTS = 2


def build_request(jpeg: bytes) -> ChatRequest:
    image = {"type": "image", "source": {
        "type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(jpeg).decode("ascii"),
    }}
    return ChatRequest(
        messages=[{"role": "user", "content": [image, {"type": "text", "text": FRIDGE_PROMPT}]}],
        output_schema=FRIDGE_SCHEMA,
        max_tokens=get_settings().llm_max_tokens,
    )


async def scan_fridge(llm: LLMProvider, jpeg: bytes, used: list[Usage]) -> FridgeScan | None:
    """読み取れたら FridgeScan、形が崩れていた・打ち切られたら None。"""
    req = build_request(jpeg)
    for _ in range(MAX_ATTEMPTS):
        result = await llm.complete(req)
        used.append(result.usage)
        if result.stop_reason == "max_tokens":
            return None
        try:
            return FridgeScan.model_validate_json(result.text)
        except ValidationError:
            continue
    return None
