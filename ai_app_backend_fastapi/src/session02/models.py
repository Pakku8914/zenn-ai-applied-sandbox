"""入出力の型（Pydantic v2）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RecipeQuery(BaseModel):
    """GET /api/recipes のクエリ。知らないパラメータ（綴り違いなど）は 422 にする。"""

    model_config = ConfigDict(extra="forbid")

    ingredient: str | None = Field(default=None, min_length=1, max_length=30, description="食材名（部分一致）")
    max_minutes: int | None = Field(default=None, ge=1, le=180, description="調理時間の上限（分）")
    tag: list[str] = Field(default=[], description="タグ。複数指定したときはすべて含むもの（AND）")
    limit: int = Field(default=20, ge=1, le=100, description="返す件数の上限")


class RecipeSummary(BaseModel):
    id: str
    name: str
    minutes: int
    kcal: int
    tags: list[str]


class RecipeList(BaseModel):
    total: int
    recipes: list[RecipeSummary]


class Ingredient(BaseModel):
    name: str
    amount: int | float
    unit: str


class RecipeDetail(RecipeSummary):
    servings: int
    ingredients: list[Ingredient]
    steps: list[str]
    allergens: list[str]


class ConsultationIn(BaseModel):
    """POST /api/consultations の本文。前後の空白は落とし、知らない項目は 422 にする。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    user_id: str = Field(pattern=r"^u\d{3}$")
    message: str = Field(min_length=1, max_length=500)
    max_minutes: int | None = Field(default=None, ge=1, le=180)


class ConsultationOut(BaseModel):
    user_id: str
    household_size: int
    allergies: list[str]
    message: str
    max_minutes: int | None
    received_at: datetime
