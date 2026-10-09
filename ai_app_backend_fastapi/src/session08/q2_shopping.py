"""練習問題2の解答：make_shopping_list（セッション8で決めたツールの規則どおり。tools.py の同名関数と同じ結果になる）。"""

from __future__ import annotations

from decimal import Decimal

from .tools import MakeShoppingListIn, ToolContext, ToolError, half_up


def make_shopping_list(args: MakeShoppingListIn, ctx: ToolContext) -> dict:
    # ① 先に全部の ID を確かめる（途中まで足してから失敗しない）
    missing = [rid for rid in args.recipe_ids if ctx.recipe(rid) is None]
    if missing:
        raise ToolError(f"レシピ {', '.join(missing)} はありません。search_recipes の結果にある id を指定してください。")
    have = set(args.have)
    totals: dict[tuple[str, str], Decimal] = {}
    for rid in args.recipe_ids:
        recipe = ctx.recipe(rid)
        assert recipe is not None
        # ② 人数の比例換算は Decimal で（4/3 のような割り切れない倍率でも、丸めは最後の1回だけ）
        scale = Decimal(args.servings) / Decimal(recipe["servings"]) if args.servings else Decimal(1)
        for ing in recipe["ingredients"]:
            if ing["name"] in have:  # ③ 家にある食材は名前の完全一致で除く
                continue
            key = (ing["name"], ing["unit"])  # ④ 同名・同単位だけを合算する
            totals[key] = totals.get(key, Decimal(0)) + Decimal(str(ing["amount"])) * scale
    # ⑤ 合算してから丸め、(name, unit) の昇順に並べる
    return {"items": [{"name": n, "amount": half_up(t, "0.01"), "unit": u} for (n, u), t in sorted(totals.items())]}
