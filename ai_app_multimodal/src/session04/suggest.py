"""冷蔵庫の写真 → 食材リスト → 要確認を除く → search_recipes、を1回通して表示する。

    docker compose exec api python -m src.session04.suggest
"""

from __future__ import annotations

import asyncio

from anthropic import AsyncAnthropic

from kondate.llm import AnthropicProvider
from kondate.media import media_path
from src.session04.intake import accept_image
from src.session04.recipes import search_recipes, to_search_args
from src.session04.review import confirmed_names, find_issues
from src.session04.scan import scan_fridge

MAX_MINUTES = 20


async def main() -> None:
    prepared = accept_image(media_path("fridge.jpg").read_bytes())
    client = AsyncAnthropic()
    try:
        result = await scan_fridge(AnthropicProvider(client), prepared.data)
    finally:
        await client.close()

    ingredients = result.scan.ingredients
    issues = find_issues(ingredients)
    print(f"読み取り: {'、'.join(i.name for i in ingredients)}（要確認 {len(issues)} 件）")
    names = confirmed_names(ingredients, issues)
    if not names:
        print("確認済みの食材が無いので、レシピは探しません")
        return
    args = to_search_args(names, max_minutes=MAX_MINUTES)
    print(f"search_recipes の入力: {args.model_dump(exclude_defaults=True)}")
    for r in search_recipes(args)["recipes"]:
        print(f"  {r['id']} {r['name']}（{r['minutes']}分・{r['kcal']}kcal）")


if __name__ == "__main__":
    asyncio.run(main())
