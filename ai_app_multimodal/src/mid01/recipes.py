"""レシピ検索 search_recipes（セッション4の recipes.py と同じ）。

規則：食材は「レシピ側の食材名が指定語を含む」部分一致。指定語のうち一致した数の多い順、
同数なら minutes の昇順、さらに id の昇順（決定的）。tags は指定したものをすべて含む（AND）。
limit は既定 5・上限 10。recipes を渡すと、その中だけを探す。
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from kondate.data import load_recipes

Allergen = Literal["卵", "乳", "小麦", "えび", "かに", "落花生", "そば"]
Word = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
MAX_INGREDIENTS = 10


class SearchRecipesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredients: list[Word] = Field(default_factory=list, max_length=MAX_INGREDIENTS, description="使いたい食材（部分一致）")
    max_minutes: int | None = Field(default=None, ge=1, le=240, description="調理時間の上限（分）")
    exclude_allergens: list[Allergen] = Field(default_factory=list, description="除外するアレルゲン")
    tags: list[Word] = Field(default_factory=list, max_length=5, description="すべて含むタグ（和食・主菜・時短 など）")
    limit: int = Field(default=5, ge=1, le=10, description="返す件数")


def search_recipes(args: SearchRecipesIn, recipes: tuple[dict, ...] | None = None) -> dict:
    words = list(dict.fromkeys(args.ingredients))
    hits: list[tuple[int, dict]] = []
    for r in recipes if recipes is not None else load_recipes():
        if args.max_minutes is not None and r["minutes"] > args.max_minutes:
            continue
        if set(args.exclude_allergens) & set(r["allergens"]):
            continue
        if not set(args.tags) <= set(r["tags"]):
            continue
        names = [i["name"] for i in r["ingredients"]]
        matched = sum(1 for w in words if any(w in n for n in names))
        if words and matched == 0:
            continue
        hits.append((matched, r))
    hits.sort(key=lambda h: (-h[0], h[1]["minutes"], h[1]["id"]))
    return {"recipes": [{k: r[k] for k in ("id", "name", "minutes", "kcal", "tags")} for _, r in hits[: args.limit]]}
