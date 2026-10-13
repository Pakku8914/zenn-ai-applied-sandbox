"""冷蔵庫の写真から読み取る食材リストの形（セッション4）。

1つの Pydantic モデルから、LLM に渡すスキーマ（transform_schema）と、応答の再検証の両方を作る。
"""

from __future__ import annotations

from typing import Annotated

from anthropic import transform_schema
from pydantic import BaseModel, Field, StringConstraints

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


# API が受け付ける形に変換したスキーマ。ChatRequest.output_schema にそのまま渡す
FRIDGE_SCHEMA = transform_schema(FridgeScan)
