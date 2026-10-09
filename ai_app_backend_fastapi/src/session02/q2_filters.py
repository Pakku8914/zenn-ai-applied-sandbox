"""練習問題2：GET /api/recipes に exclude_allergen（複数可）と sort を足す。"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from src.session02.deps import StoreDep
from src.session02.models import RecipeList, RecipeQuery

router = APIRouter(tags=["recipes"])


class RecipeQueryV2(RecipeQuery):  # extra="forbid" も引き継ぐ
    exclude_allergen: list[str] = []
    sort: Literal["id", "minutes"] = "id"


@router.get("/api/recipes", response_model=RecipeList)
async def list_recipes(q: Annotated[RecipeQueryV2, Query()], store: StoreDep) -> dict[str, object]:
    hits = store.find_recipes(ingredient=q.ingredient, max_minutes=q.max_minutes, tags=q.tag)
    if q.exclude_allergen:
        banned = set(q.exclude_allergen)
        hits = [r for r in hits if banned.isdisjoint(r["allergens"])]
    if q.sort == "minutes":
        hits = sorted(hits, key=lambda r: (r["minutes"], r["id"]))  # 同じ分数は id 順（決定的）
    return {"total": len(hits), "recipes": hits[: q.limit]}
