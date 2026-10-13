"""問題5：食材リストの応答（API の JSON）を search_recipes の入力につなぐ。

    docker compose exec api python -m src.session04.solutions.q5_suggest
"""

from __future__ import annotations

import asyncio

import httpx2
from anthropic import AsyncAnthropic

from kondate.llm import AnthropicProvider
from kondate.media import media_path
from src.session04.app import app, get_llm
from src.session04.recipes import search_recipes, to_search_args
from src.session04.review import MSG_LOW_CONFIDENCE

MAX_MINUTES = 20


def suggest(body: dict, max_minutes: int | None = None) -> tuple[list[str], list[str], list[dict]]:
    """（渡す食材, 除いた食材, レシピ）。要確認の印が付いた食材は渡さない。"""
    flagged = {issue["index"] for issue in body["issues"]}
    names: list[str] = []
    skipped: list[str] = []
    for index, ing in enumerate(body["ingredients"]):
        (skipped if index in flagged else names).append(ing["name"])
    names = list(dict.fromkeys(names))
    if not names:
        return names, skipped, []  # 何も渡さずに検索すると、全レシピから選んでしまう
    return names, skipped, search_recipes(to_search_args(names, max_minutes))["recipes"]


async def scan_via_api() -> dict:
    client = AsyncAnthropic()
    app.dependency_overrides[get_llm] = lambda: AnthropicProvider(client)
    try:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/fridge/scan", files={"image": ("fridge.jpg", media_path("fridge.jpg").read_bytes(), "image/jpeg")})
    finally:
        app.dependency_overrides.clear()
        await client.close()
    r.raise_for_status()
    return r.json()


def show(title: str, body: dict) -> None:
    names, skipped, recipes = suggest(body, MAX_MINUTES)
    print(f"{title}:")
    print(f"  渡す食材: {'、'.join(names) or 'なし'}（除いた食材: {'、'.join(skipped) or 'なし'}）")
    for r in recipes:
        print(f"  {r['id']} {r['name']}（{r['minutes']}分）")


def main() -> None:
    body = asyncio.run(scan_via_api())
    show("写真の読み取り結果から", body)
    carrot = {"index": 3, "name": "にんじん", "reason": "low_confidence", "message": MSG_LOW_CONFIDENCE}
    show("にんじんが要確認の応答から", {**body, "needs_review": True, "issues": [carrot]})


if __name__ == "__main__":
    main()
