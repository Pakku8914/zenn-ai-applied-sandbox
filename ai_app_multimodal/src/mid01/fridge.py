"""冷蔵庫の写真から食材リスト（セッション4の models.py・scan.py・review.py を1つにまとめたもの。中身は同じ）。"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

import anthropic
from anthropic import transform_schema
from pydantic import BaseModel, Field, StringConstraints, ValidationError

from kondate.data import load_recipes
from kondate.llm import ChatRequest, LLMProvider, Usage
from kondate.settings import get_settings

log = logging.getLogger(__name__)

MSG_INVALID_OUTPUT = "読み取り結果の形式が正しくありませんでした"
MSG_UPSTREAM = "画像の読み取りに失敗しました。時間をおいて試してください"


# ---------------------------------------------------------------- 形（models.py）

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class Ingredient(BaseModel):
    name: Name = Field(description="食材の名前（例：キャベツ）")
    quantity: str = Field(description="見た目の分量（例：1/2玉）")
    amount: float = Field(gt=0, description="数量（例：0.5）")
    unit: str = Field(description="数量の単位（例：玉）")
    confidence: float = Field(ge=0, le=1, description="読み取りの確からしさ（0〜1）")
    category: str = Field(description="食材の分類（例：野菜）")


class FridgeScan(BaseModel):
    ingredients: list[Ingredient]


FRIDGE_SCHEMA = transform_schema(FridgeScan)


# ---------------------------------------------------------------- 読み取り（scan.py）

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
    usage: Usage  # すべての試行の合計


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


# ---------------------------------------------------------------- 要確認（review.py）

REVIEW_CONFIDENCE = 0.6
MSG_LOW_CONFIDENCE = "読み取りの確からしさが低い食材です。写真と合っているか確かめてください"
MSG_UNKNOWN_NAME = "食材辞書にない名前です。名前が正しいか確かめてください"


@lru_cache
def ingredient_dictionary() -> frozenset[str]:
    """レシピデータに出てくる食材名の集合。ここに無い名前では、レシピを探しても見つからない。"""
    return frozenset(i["name"] for r in load_recipes() for i in r["ingredients"])


def find_issues(ingredients: list[Ingredient]) -> list[dict]:
    known = ingredient_dictionary()
    issues: list[dict] = []
    for index, ing in enumerate(ingredients):
        if ing.confidence < REVIEW_CONFIDENCE:
            issues.append({"index": index, "name": ing.name, "reason": "low_confidence", "message": MSG_LOW_CONFIDENCE})
        if ing.name not in known:
            issues.append({"index": index, "name": ing.name, "reason": "unknown_name", "message": MSG_UNKNOWN_NAME})
    return issues
