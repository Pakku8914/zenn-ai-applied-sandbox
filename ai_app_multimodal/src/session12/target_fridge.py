"""評価対象①：冷蔵庫の写真 → 食材リスト（セッション4のコードから、評価に要る部分だけを写したもの）。

前処理（向き・縮小・EXIF を捨てた JPEG）→ 構造化出力 → Pydantic で再検証（形が崩れたら1回だけ再試行）→ 要確認の印付け。
HTTP の受付とエラー応答は評価に関係しないので写していない。
"""

from __future__ import annotations

import base64
import io
from functools import lru_cache
from typing import Annotated

import anthropic
from anthropic import transform_schema
from PIL import Image, ImageOps
from pydantic import BaseModel, Field, StringConstraints, ValidationError

from kondate.data import load_recipes
from kondate.llm import ChatRequest, LLMProvider
from kondate.settings import get_settings

FRIDGE_PROMPT = "冷蔵庫の写真に写っている食材をすべて挙げてください。分量が分からないものは見た目から推定してください。"
MAX_ATTEMPTS = 2
REVIEW_CONFIDENCE = 0.6

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


class UpstreamUnavailable(Exception):
    """LLM の API から応答を得られなかった。"""


class InvalidOutput(Exception):
    """応答はあったが、食材リストとして使えなかった。"""


def prepare_image(raw: bytes) -> bytes:
    """向きを直し、長辺を上限まで縮め、EXIF を捨てた JPEG にする（セッション3）。"""
    limit = get_settings().image_max_long_edge
    with Image.open(io.BytesIO(raw)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((limit, limit))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


def build_request(jpeg: bytes) -> ChatRequest:
    image = {"type": "image", "source": {
        "type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(jpeg).decode("ascii"),
    }}
    return ChatRequest(
        messages=[{"role": "user", "content": [image, {"type": "text", "text": FRIDGE_PROMPT}]}],
        output_schema=FRIDGE_SCHEMA,
        max_tokens=get_settings().llm_max_tokens,
    )


async def scan_fridge(llm: LLMProvider, jpeg: bytes) -> FridgeScan:
    req = build_request(jpeg)
    for _ in range(MAX_ATTEMPTS):
        try:
            result = await llm.complete(req)
        except anthropic.APIError as e:
            raise UpstreamUnavailable() from e
        if result.stop_reason == "max_tokens":
            raise InvalidOutput("max_tokens")
        try:
            return FridgeScan.model_validate_json(result.text)
        except ValidationError:
            continue
    raise InvalidOutput("validation")


@lru_cache
def ingredient_dictionary() -> frozenset[str]:
    return frozenset(i["name"] for r in load_recipes() for i in r["ingredients"])


def find_issues(ingredients: list[Ingredient]) -> list[dict]:
    """要確認の印（セッション4と同じ基準）。評価では index・name・reason だけを使う。"""
    known = ingredient_dictionary()
    issues: list[dict] = []
    for index, ing in enumerate(ingredients):
        if ing.confidence < REVIEW_CONFIDENCE:
            issues.append({"index": index, "name": ing.name, "reason": "low_confidence"})
        if ing.name not in known:
            issues.append({"index": index, "name": ing.name, "reason": "unknown_name"})
    return issues
