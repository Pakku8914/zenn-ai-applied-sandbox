"""問題4：失敗の種類ごとに、再試行するか・何を返すかを確かめる。

    docker compose exec api python -m src.session04.solutions.q4_retry
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import httpx2
from anthropic import AsyncAnthropic

from kondate.llm import AnthropicProvider, ChatRequest, ChatResult, FakeProvider, LLMProvider, StreamEvent, Usage
from kondate.media import media_path
from kondate.settings import get_settings
from src.session04.app import app, get_llm

logging.getLogger("src.session04").setLevel(logging.ERROR)  # 失敗をわざと作るので、scan の警告ログは表示しない

FRIDGE = media_path("fridge.jpg").read_bytes()
MOCK = get_settings().mockllm_url
NAMES = ["キャベツ", "鶏むね肉", "卵", "にんじん", "牛乳"]


def answer(confidence: float = 0.9) -> ChatResult:
    items = [{"name": n, "quantity": "1個", "amount": 1, "unit": "個", "confidence": confidence, "category": "野菜"} for n in NAMES]
    return ChatResult(json.dumps({"ingredients": items}, ensure_ascii=False), [], "end_turn", Usage(1668, 120))


CUT = ChatResult('{"ingredients": [{"name": "キャ', [], "max_tokens", Usage(1668, 100))

CASES = [
    ("A 正常な JSON", [answer()]),
    ("B 範囲外の confidence → 正常", [answer(1.5), answer()]),
    ("C 範囲外の confidence が2回続く", [answer(1.5), answer(1.5)]),  # 3回目を呼んだら FakeProvider が例外を出す
    ("D max_tokens で切れた JSON", [CUT, answer()]),                   # 2つ目は使われないはず
]


class Counting:
    """LLMProvider を包み、アプリが complete を呼んだ回数を数える。"""

    name = "counting"

    def __init__(self, inner: LLMProvider) -> None:
        self.inner, self.calls = inner, 0

    async def complete(self, req: ChatRequest) -> ChatResult:
        self.calls += 1
        return await self.inner.complete(req)

    def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        return self.inner.stream(req)


async def post(llm: LLMProvider) -> httpx2.Response:
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as c:
            return await c.post("/api/fridge/scan", files={"image": ("fridge.jpg", FRIDGE, "image/jpeg")})
    finally:
        app.dependency_overrides.clear()


def describe(r: httpx2.Response) -> str:
    return "200" if r.status_code == 200 else f"{r.status_code} {r.json()['error']['type']}"


async def run() -> None:
    for label, results in CASES:
        fake = FakeProvider(results)
        r = await post(fake)
        print(f"{label} → {describe(r)}（LLM を呼んだ回数 {len(fake.requests)}）")

    async with httpx2.AsyncClient(base_url=MOCK) as c:
        await c.post("/_mock/reset")
    client = AsyncAnthropic(default_headers={"x-mock-fault": "529"})  # SDK の既定の再試行（2回）はそのまま
    counting = Counting(AnthropicProvider(client))
    try:
        r = await post(counting)
    finally:
        await client.close()
    async with httpx2.AsyncClient(base_url=MOCK) as c:
        received = (await c.get("/_mock/stats")).json()["by_status"].get("529", 0)
    print(f"E 上流が 529 を返し続ける → {describe(r)}（アプリの呼び出し {counting.calls}・mockllm が受けた回数 {received}）")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
