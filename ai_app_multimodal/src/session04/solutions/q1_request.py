"""問題1：自分で定義した Pydantic モデルから構造化出力のスキーマを作り、fridge.jpg を送る。

    docker compose exec api python -m src.session04.solutions.q1_request
"""

from __future__ import annotations

import asyncio
import base64

from anthropic import AsyncAnthropic, transform_schema
from pydantic import BaseModel, Field

from kondate.llm import AnthropicProvider, ChatRequest
from kondate.media import media_path
from kondate.settings import get_settings
from src.session04.intake import accept_image

PROMPT = "冷蔵庫の写真に写っている食材をすべて挙げてください。分量が分からないものは見た目から推定してください。"


class LiteItem(BaseModel):
    name: str
    amount: float
    unit: str
    confidence: float = Field(ge=0, le=1)


class LiteScan(BaseModel):
    ingredients: list[LiteItem]


def build(jpeg: bytes, schema: dict) -> ChatRequest:
    image = {"type": "image", "source": {
        "type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(jpeg).decode("ascii"),
    }}
    return ChatRequest(
        messages=[{"role": "user", "content": [image, {"type": "text", "text": PROMPT}]}],
        output_schema=schema,
        max_tokens=get_settings().llm_max_tokens,
    )


async def run() -> None:
    schema = transform_schema(LiteScan)
    item = schema["$defs"]["LiteItem"]
    raw_conf = LiteScan.model_json_schema()["$defs"]["LiteItem"]["properties"]["confidence"]
    print(f"必須の項目: {', '.join(item['required'])}")
    print(f"additionalProperties: {item['additionalProperties']}")
    print(f"confidence の範囲（変換前）: minimum={raw_conf['minimum']}・maximum={raw_conf['maximum']}")
    left = "残っている" if "minimum" in item["properties"]["confidence"] else "外された"
    print(f"confidence の範囲（変換後）: {left}")

    jpeg = accept_image(media_path("fridge.jpg").read_bytes()).data
    client = AsyncAnthropic()
    try:
        result = await AnthropicProvider(client).complete(build(jpeg, schema))
    finally:
        await client.close()
    scan = LiteScan.model_validate_json(result.text)  # 形は保証されていても、値は自分で確かめる
    for i in scan.ingredients:
        print(f"{i.name} {i.amount:g}{i.unit}（{i.confidence}）")
    print(f"input_tokens={result.usage.input_tokens}")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
