"""こんだてAI の6つのツール。5つは mid01/tools.py（＝session08）のコピーで、plan_week だけを足した。

- plan_week はその場で献立を作らない。ジョブを積み、{job_id, status: "queued"} を返す（API契約④）
- 利用者 ID は LLM に渡させない。ToolContext に入っている「認証した利用者」のジョブとして積む
  （plan_week の入力 user_id は、ジョブの持ち主のこと。LLM が決めてよい値ではない）
"""

from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from uuid_utils import uuid7

from kondate.clock import Clock
from kondate.data import load_recipes

Allergen = Literal["卵", "乳", "小麦", "えび", "かに", "落花生", "そば"]
Unit = Literal["g", "kg", "ml", "l", "大さじ", "小さじ", "カップ"]
Word = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
RecipeId = Annotated[str, StringConstraints(pattern=r"^R\d{3}$")]

GRAMS = {"g": Decimal(1), "kg": Decimal(1000)}
MILLILITERS = {"ml": Decimal(1), "l": Decimal(1000), "大さじ": Decimal(15), "小さじ": Decimal(5), "カップ": Decimal(200)}

PlanWeekLauncher = Callable[[int], Awaitable[dict]]


class ToolError(Exception):
    """LLM に is_error: true で返す想定内の失敗。文は LLM が読んで直せる日本語にし、内部の情報は入れない。"""


@dataclass(frozen=True)
class ToolContext:
    """ツールが使ってよい外の世界。時計・データと、ジョブを積む関数（認証した利用者に結び付いたもの）。"""

    clock: Clock
    recipes: tuple[dict, ...] = field(default_factory=load_recipes)
    launch_plan_week: PlanWeekLauncher | None = None

    def recipe(self, recipe_id: str) -> dict | None:
        return next((r for r in self.recipes if r["id"] == recipe_id), None)


def half_up(value: Decimal, places: str) -> int | float:
    q = value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return int(q) if q == q.to_integral_value() else float(q)


# ---------------------------------------------------------------- 入力のモデル


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchRecipesIn(ToolInput):
    ingredients: list[Word] = Field(default_factory=list, max_length=10, description="使いたい食材（部分一致）")
    max_minutes: int | None = Field(default=None, ge=1, le=240, description="調理時間の上限（分）")
    exclude_allergens: list[Allergen] = Field(default_factory=list, description="除外するアレルゲン")
    tags: list[Word] = Field(default_factory=list, max_length=5, description="すべて含むタグ（和食・主菜・時短 など）")
    limit: int = Field(default=5, ge=1, le=10, description="返す件数")


class GetRecipeIn(ToolInput):
    recipe_id: RecipeId = Field(description="R001 形式のレシピ ID")


class ConvertUnitsIn(ToolInput):
    amount: float = Field(gt=0, le=100000)
    from_unit: Unit
    to_unit: Unit


class SetTimerIn(ToolInput):
    minutes: int = Field(ge=1, le=180)
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class MakeShoppingListIn(ToolInput):
    recipe_ids: list[RecipeId] = Field(min_length=1, max_length=10)
    servings: int | None = Field(default=None, ge=1, le=20, description="作る人数（省略時はレシピの人数）")
    have: list[Word] = Field(default_factory=list, max_length=30, description="家にある食材（名前が同じものを除く）")


class PlanWeekIn(ToolInput):
    days: int = Field(default=7, ge=1, le=14, description="何日分の献立を作るか（既定 7）")


# ---------------------------------------------------------------- ツールの本体


def match_recipes(args: SearchRecipesIn, recipes: tuple[dict, ...]) -> list[tuple[int, dict]]:
    words = list(dict.fromkeys(args.ingredients))
    hits: list[tuple[int, dict]] = []
    for r in recipes:
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
    return hits


def search_recipes(args: SearchRecipesIn, ctx: ToolContext) -> dict:
    hits = match_recipes(args, ctx.recipes)[: args.limit]
    return {"recipes": [{k: r[k] for k in ("id", "name", "minutes", "kcal", "tags")} for _, r in hits]}


def get_recipe(args: GetRecipeIn, ctx: ToolContext) -> dict:
    recipe = ctx.recipe(args.recipe_id)
    if recipe is None:
        raise ToolError(f"レシピ {args.recipe_id} はありません。search_recipes の結果にある id を指定してください。")
    return copy.deepcopy(recipe)


def convert_units(args: ConvertUnitsIn, ctx: ToolContext) -> dict:
    for table in (GRAMS, MILLILITERS):
        if args.from_unit in table and args.to_unit in table:
            value = Decimal(str(args.amount)) * table[args.from_unit] / table[args.to_unit]
            return {"amount": half_up(value, "0.1"), "unit": args.to_unit}
    raise ToolError(f"{args.from_unit} と {args.to_unit} は換算できません（重さと体積の換算はしません）。")


def set_timer(args: SetTimerIn, ctx: ToolContext) -> dict:
    ends_at = ctx.clock.now() + timedelta(minutes=args.minutes)
    return {"timer_id": f"timer_{uuid7()}", "label": args.label, "ends_at": ends_at.isoformat()}


def make_shopping_list(args: MakeShoppingListIn, ctx: ToolContext) -> dict:
    missing = [rid for rid in args.recipe_ids if ctx.recipe(rid) is None]
    if missing:
        raise ToolError(f"レシピ {', '.join(missing)} はありません。search_recipes の結果にある id を指定してください。")
    have = set(args.have)
    totals: dict[tuple[str, str], Decimal] = {}
    for rid in args.recipe_ids:
        recipe = ctx.recipe(rid)
        assert recipe is not None
        scale = Decimal(args.servings) / Decimal(recipe["servings"]) if args.servings else Decimal(1)
        for ing in recipe["ingredients"]:
            if ing["name"] in have:
                continue
            key = (ing["name"], ing["unit"])
            totals[key] = totals.get(key, Decimal(0)) + Decimal(str(ing["amount"])) * scale
    items = [{"name": name, "amount": half_up(total, "0.01"), "unit": unit}
             for (name, unit), total in sorted(totals.items())]
    return {"items": items}


async def plan_week(args: PlanWeekIn, ctx: ToolContext) -> dict:
    """ジョブを積んで、すぐに {job_id, status: "queued"} を返す（献立ができるのを待たない）。"""
    if ctx.launch_plan_week is None:
        raise ToolError("いまは1週間の献立づくりを受け付けられません。日ごとの献立を提案してください。")
    return await ctx.launch_plan_week(args.days)


# ---------------------------------------------------------------- 登録簿


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[ToolInput]
    run: Callable[[Any, ToolContext], dict | Awaitable[dict]]
    timeout_s: float | None = None


TOOLS: Mapping[str, Tool] = {t.name: t for t in (
    Tool("search_recipes", "食材・調理時間・アレルゲン・タグでレシピを探す。一致する食材が多い順に返す。",
         SearchRecipesIn, search_recipes),
    Tool("get_recipe", "レシピ ID から、材料と手順を含むレシピ1件を返す。", GetRecipeIn, get_recipe),
    Tool("convert_units", "分量の単位を換算する（g・kg・ml・l・大さじ・小さじ・カップ。重さと体積の換算はしない）。",
         ConvertUnitsIn, convert_units),
    Tool("set_timer", "調理用のタイマーを設定し、終わる時刻を返す。", SetTimerIn, set_timer),
    Tool("make_shopping_list", "レシピ ID の一覧から、人数に合わせた買い物リストを作る。", MakeShoppingListIn,
         make_shopping_list),
    Tool("plan_week", "利用者のアレルギーを除いた、数日分の献立づくりをバックグラウンドで始める。"
                      "結果はすぐには返らず、ジョブの ID を返す。", PlanWeekIn, plan_week),
)}


def tool_definitions(tools: Mapping[str, Tool] = TOOLS) -> list[dict]:
    return [{"name": t.name, "description": t.description, "input_schema": t.input_model.model_json_schema()}
            for t in tools.values()]
