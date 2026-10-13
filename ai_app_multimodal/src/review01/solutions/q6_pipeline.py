"""問題6：受付から要確認までを1本の関数にし、8種類の入力で状態コード・LLM の呼び出し回数・usage を確かめる。

    docker compose exec api python -m src.review01.solutions.q6_pipeline
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

import anyio
import httpx2
from anthropic import AsyncAnthropic

from kondate.llm import AnthropicProvider, ChatRequest, ChatResult, FakeProvider, LLMProvider, StreamEvent, Usage
from kondate.settings import get_settings
from src.review01 import samples
from src.review01.kit import (
    MSG_INVALID_OUTPUT, MSG_UPSTREAM, SCAN_MSG_TOO_LARGE, UPLOAD_MAX_BYTES,
    InvalidOutput, Rejected, UpstreamUnavailable, accept_image, find_issues, scan_fridge,
)

logging.getLogger("src.review01").setLevel(logging.ERROR)

MOCK = get_settings().mockllm_url
NO_USAGE = Usage(0, 0)


@dataclass(frozen=True)
class Outcome:
    status: int
    body: dict    # 利用者に返す本文（request_id は HTTP の層で足す）
    usage: Usage  # 記録用。502 でも、試行したぶんの合計が入る


def failure(status: int, type_: str, message: str, usage: Usage = NO_USAGE) -> Outcome:
    return Outcome(status, {"error": {"type": type_, "message": message}}, usage)


async def scan_pipeline(raw: bytes, llm: LLMProvider) -> Outcome:
    if len(raw) > UPLOAD_MAX_BYTES:  # セッション2：数えるだけで済む検査を最初に
        return failure(413, "too_large", SCAN_MSG_TOO_LARGE)
    try:
        prepared = await anyio.to_thread.run_sync(accept_image, raw)  # セッション2・3：中身の検査と前処理
    except Rejected as e:
        return failure(e.status, e.type, e.message)
    try:
        result = await scan_fridge(llm, prepared.data)  # セッション4：再検証と再試行
    except UpstreamUnavailable:
        return failure(503, "upstream_unavailable", MSG_UPSTREAM)
    except InvalidOutput as e:
        return failure(502, "invalid_output", MSG_INVALID_OUTPUT, e.usage)
    issues = find_issues(result.scan.ingredients)
    return Outcome(200, {
        "ingredients": [i.model_dump() for i in result.scan.ingredients],
        "needs_review": bool(issues),
        "issues": issues,
        "image": prepared.info(),
        "usage": {"input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens},
    }, result.usage)


class Counting:
    """LLMProvider を包み、complete が呼ばれた回数を数える。"""

    name = "counting"

    def __init__(self, inner: LLMProvider) -> None:
        self.inner, self.calls = inner, 0

    async def complete(self, req: ChatRequest) -> ChatResult:
        self.calls += 1
        return await self.inner.complete(req)

    def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        return self.inner.stream(req)


def out_of_range() -> ChatResult:
    items = [{"name": n, "quantity": "1個", "amount": 1, "unit": "個", "confidence": 1.5, "category": "野菜"}
             for n in ["キャベツ", "鶏むね肉", "卵", "にんじん", "牛乳"]]
    return ChatResult(json.dumps({"ingredients": items}, ensure_ascii=False), [], "end_turn", Usage(1668, 194))


def summary(o: Outcome) -> str:
    if o.status == 200:
        return f"200 食材 {len(o.body['ingredients'])} 件・要確認 {len(o.body['issues'])} 件"
    err = o.body["error"]
    return f"{o.status} {err['type']}「{err['message']}」"


async def run() -> None:
    async with httpx2.AsyncClient(base_url=MOCK) as c:
        await c.post("/_mock/reset")
    client = AsyncAnthropic()
    faulty = AsyncAnthropic(default_headers={"x-mock-fault": "529"}, max_retries=0)
    mock = AnthropicProvider(client)
    cases: list[tuple[str, bytes, LLMProvider]] = [
        ("fridge.jpg", samples.fridge(), mock),
        ("縦向きの写真", samples.portrait(), mock),
        ("4000×3000 の写真", samples.large(), mock),
        ("recipe_book.pdf", samples.recipe_pdf(), mock),
        ("8000×6000 の PNG", samples.huge_png(), mock),
        ("10MiB を1バイト超えるファイル", samples.oversize(), mock),
        ("範囲外の confidence が2回続く", samples.fridge(), FakeProvider([out_of_range(), out_of_range()])),
        ("上流が 529 を返す", samples.fridge(), AnthropicProvider(faulty)),
    ]
    try:
        for label, raw, llm in cases:
            counting = Counting(llm)
            o = await scan_pipeline(raw, counting)
            print(f"{label} → {summary(o)}・usage {o.usage.input_tokens}/{o.usage.output_tokens}・LLM {counting.calls} 回")
    finally:
        await client.close()
        await faulty.close()
    async with httpx2.AsyncClient(base_url=MOCK) as c:
        by_status = (await c.get("/_mock/stats")).json()["by_status"]
    print(f"mockllm が返した状態コード: {'・'.join(f'{k}×{v}' for k, v in sorted(by_status.items()))}")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
