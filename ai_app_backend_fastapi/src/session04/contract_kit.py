"""契約テストの部品：テスト対象のプロバイダを名前から用意する。接続先は必ず mockllm にする。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager

from kondate.settings import get_settings

from .providers import (ChatRequest, FakeItem, FakeProvider, LLMProvider, ProviderError, StreamEvent,
                        TextDelta, ToolCall, Usage, fake_script, open_provider)

PROVIDERS = ["anthropic", "openai", "fake"]
PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"
TOOLS = [
    {"name": "search_recipes", "description": "食材や調理時間からレシピを探す",
     "input_schema": {"type": "object", "properties": {
         "ingredients": {"type": "array", "items": {"type": "string"}},
         "max_minutes": {"type": "integer"},
         "exclude_allergens": {"type": "array", "items": {"type": "string"}},
         "tags": {"type": "array", "items": {"type": "string"}},
         "limit": {"type": "integer"}}}},
    {"name": "get_recipe", "description": "レシピ ID（R001 形式）から1件を取り出す",
     "input_schema": {"type": "object", "properties": {"recipe_id": {"type": "string"}},
                      "required": ["recipe_id"]}},
]
TEXT_REQ = ChatRequest(messages=[{"role": "user", "content": PROMPT}])
TOOL_REQ = ChatRequest(messages=[{"role": "user", "content": PROMPT}], tools=TOOLS)
SEARCH_INPUT = {"ingredients": ["鶏むね肉", "キャベツ"], "max_minutes": 20}
TOOL_RESULT = '{"recipes": [{"id": "R001", "name": "鶏むね肉とキャベツの塩炒め"}]}'  # 本物の検索は後のセッションで

# Fake 用の台本（本物の2つと同じ契約を満たす形にしておく）
FAKE_TEXT = fake_script("鶏むね肉とキャベツの塩炒めがおすすめです。", usage=Usage(34, 20))
FAKE_TOOL = fake_script("条件に合うレシピを探しますね。", usage=Usage(300, 42),
                        tool_calls=[ToolCall("toolu_fake_1", "search_recipes", SEARCH_INPUT)])
FAKE_GET = fake_script("作り方を確認します。", usage=Usage(400, 30),
                       tool_calls=[ToolCall("toolu_fake_2", "get_recipe", {"recipe_id": "R001"})])
FAKE_RATE_LIMITED = [ProviderError("rate_limited", provider="fake", status_code=429)]
FAKE_STREAM_ERROR = [TextDelta("鶏むね肉とキ"), TextDelta("ャベツがある"),
                     ProviderError("stream_error", provider="fake", status_code=200)]


@asynccontextmanager
async def provider_under_test(name: str, *fake_scripts: Sequence[FakeItem],
                              fault: str | None = None) -> AsyncIterator[LLMProvider]:
    """name のプロバイダを返す。fake なら台本を使い、本物なら mockllm に向け、fault を障害注入ヘッダで送る。"""
    if name == "fake":
        yield FakeProvider(*fake_scripts)
        return
    s = get_settings()
    async with open_provider(
        name, model=s.llm_model,
        base_url=s.mockllm_url if name == "anthropic" else f"{s.mockllm_url}/v1",
        api_key="mock-key", max_retries=0, timeout=10.0,
        default_headers={"x-mock-fault": fault} if fault else None,
    ) as provider:
        yield provider


def event_shape(events: Iterable[StreamEvent]) -> str:
    """イベント列を「TextDelta×3 → ToolCallStart → …」の形に縮める（検証の出力用）。"""
    runs: list[list] = []
    for ev in events:
        kind = type(ev).__name__
        if runs and runs[-1][0] == kind:
            runs[-1][1] += 1
        else:
            runs.append([kind, 1])
    return " → ".join(k if n == 1 else f"{k}×{n}" for k, n in runs)
