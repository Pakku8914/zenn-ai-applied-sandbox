"""こんだてAI のツールのうち、サーバでその場で実行する5つ。session08/tools.py のコピー（書き換えない）。

- 入力は Pydantic のモデルで検証する。LLM へ渡す input_schema も同じモデルから作る（定義と検証を1か所に）
- 出力は決定的にする：並び順を必ず決め、丸めは ROUND_HALF_UP、時刻は注入した Clock から計算する
- 想定内の失敗（存在しない ID・換算できない単位）は ToolError を送出する。ループが is_error の結果に変える
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

Allergen = Literal["卵", "乳", "小麦", "えび", "かに", "落花生", "そば"]  # 特定原材料7品目（recipes.json と同じ）
Unit = Literal["g", "kg", "ml", "l", "大さじ", "小さじ", "カップ"]
Word = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
RecipeId = Annotated[str, StringConstraints(pattern=r"^R\d{3}$")]

GRAMS = {"g": Decimal(1), "kg": Decimal(1000)}
MILLILITERS = {"ml": Decimal(1), "l": Decimal(1000), "大さじ": Decimal(15), "小さじ": Decimal(5), "カップ": Decimal(200)}


class ToolError(Exception):
    """LLM に is_error: true で返す想定内の失敗。文は LLM が読んで直せる日本語にし、内部の情報は入れない。"""


@dataclass(frozen=True)
class ToolContext:
    """ツールが使ってよい外の世界。時計とデータを受け取る（datetime.now() やファイルを直接読まない）。"""

    clock: Clock
    recipes: tuple[dict, ...] = field(default_factory=load_recipes)

    def recipe(self, recipe_id: str) -> dict | None:
        return next((r for r in self.recipes if r["id"] == recipe_id), None)


def half_up(value: Decimal, places: str) -> int | float:
    """四捨五入（ROUND_HALF_UP）して JSON の数にする。整数になったら int（3冊で同じ JSON にそろえる）。"""
    q = value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return int(q) if q == q.to_integral_value() else float(q)


# ---------------------------------------------------------------- 入力のモデル


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 知らない引数は黙って捨てず、誤りとして LLM に返す


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


# ---------------------------------------------------------------- ツールの本体


def match_recipes(args: SearchRecipesIn, recipes: tuple[dict, ...]) -> list[tuple[int, dict]]:
    """条件に合うレシピを (一致数, レシピ) で、limit をかける前の全件を決定的な順に返す。"""
    words = list(dict.fromkeys(args.ingredients))  # 同じ語が2回来ても1回と数える
    hits: list[tuple[int, dict]] = []
    for r in recipes:
        if args.max_minutes is not None and r["minutes"] > args.max_minutes:
            continue
        if set(args.exclude_allergens) & set(r["allergens"]):
            continue
        if not set(args.tags) <= set(r["tags"]):  # タグは AND
            continue
        names = [i["name"] for i in r["ingredients"]]
        matched = sum(1 for w in words if any(w in n for n in names))  # レシピ側の食材名が指定語を含む
        if words and matched == 0:
            continue
        hits.append((matched, r))
    hits.sort(key=lambda h: (-h[0], h[1]["minutes"], h[1]["id"]))  # 一致数の多い順 → minutes → id
    return hits


def search_recipes(args: SearchRecipesIn, ctx: ToolContext) -> dict:
    hits = match_recipes(args, ctx.recipes)[: args.limit]
    return {"recipes": [{k: r[k] for k in ("id", "name", "minutes", "kcal", "tags")} for _, r in hits]}


def get_recipe(args: GetRecipeIn, ctx: ToolContext) -> dict:
    recipe = ctx.recipe(args.recipe_id)
    if recipe is None:
        raise ToolError(f"レシピ {args.recipe_id} はありません。search_recipes の結果にある id を指定してください。")
    return copy.deepcopy(recipe)  # 共有しているデータを、呼び出し側に書き換えさせない


def convert_units(args: ConvertUnitsIn, ctx: ToolContext) -> dict:
    for table in (GRAMS, MILLILITERS):
        if args.from_unit in table and args.to_unit in table:
            # float のまま掛け算しない。str を経由すると、書かれた値（0.25）そのものの Decimal になる
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
            key = (ing["name"], ing["unit"])  # 同名・同単位だけを合算する（g と 個 は足さない）
            totals[key] = totals.get(key, Decimal(0)) + Decimal(str(ing["amount"])) * scale
    items = [{"name": name, "amount": half_up(total, "0.01"), "unit": unit}
             for (name, unit), total in sorted(totals.items())]  # 合算してから丸める・name（→ unit）の昇順
    return {"items": items}


# ---------------------------------------------------------------- 登録簿


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[ToolInput]
    run: Callable[[Any, ToolContext], dict | Awaitable[dict]]
    timeout_s: float | None = None  # None ならループの既定値


TOOLS: Mapping[str, Tool] = {t.name: t for t in (
    Tool("search_recipes", "食材・調理時間・アレルゲン・タグでレシピを探す。一致する食材が多い順に返す。",
         SearchRecipesIn, search_recipes),
    Tool("get_recipe", "レシピ ID から、材料と手順を含むレシピ1件を返す。", GetRecipeIn, get_recipe),
    Tool("convert_units", "分量の単位を換算する（g・kg・ml・l・大さじ・小さじ・カップ。重さと体積の換算はしない）。",
         ConvertUnitsIn, convert_units),
    Tool("set_timer", "調理用のタイマーを設定し、終わる時刻を返す。", SetTimerIn, set_timer),
    Tool("make_shopping_list", "レシピ ID の一覧から、人数に合わせた買い物リストを作る。", MakeShoppingListIn,
         make_shopping_list),
)}


def tool_definitions(tools: Mapping[str, Tool] = TOOLS) -> list[dict]:
    """LLM に渡す定義（Anthropic 形式）。input_schema は検証に使うのと同じモデルから作る。"""
    return [{"name": t.name, "description": t.description, "input_schema": t.input_model.model_json_schema()}
            for t in tools.values()]
