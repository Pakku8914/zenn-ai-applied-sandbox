"""練習問題1の解答：SDK の自動リトライで、上流が実際に何回受けたかを mockllm の stats で数える。"""

from __future__ import annotations

from dataclasses import dataclass

import httpx2

from kondate.settings import get_settings

from .providers import ChatRequest, ProviderError, open_provider

PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"


@dataclass(frozen=True)
class Measured:
    outcome: str  # ok か、ProviderError の kind
    calls: int  # 上流（mockllm）が受けた回数
    retry_counts: list[str | None]  # SDK が付けた x-stainless-retry-count


async def measure(fault: str, times: int | None, max_retries: int | None, key: str) -> Measured:
    """fault を最初の times 回だけ注入して1回呼ぶ。max_retries=None なら SDK の既定のまま。"""
    s = get_settings()
    headers = {"x-mock-fault": fault, "x-mock-fault-key": key}
    if times is not None:
        headers["x-mock-fault-times"] = str(times)
    options = {} if max_retries is None else {"max_retries": max_retries}
    chat = ChatRequest(messages=[{"role": "user", "content": PROMPT}], max_tokens=1024)
    async with open_provider("anthropic", model=s.llm_model, base_url=s.mockllm_url, api_key="mock-key",
                             timeout=30.0, default_headers=headers, **options) as p:
        try:
            await p.complete(chat)
            outcome = "ok"
        except ProviderError as e:
            outcome = e.kind
    async with httpx2.AsyncClient(timeout=5) as c:
        slot = (await c.get(f"{s.mockllm_url}/_mock/stats")).json()["faults"][key]
    return Measured(outcome, slot["calls"], slot["retry_counts"])


def upstream_calls(sdk_retries: int, own_attempts: int) -> int:
    """SDK の自動リトライの上に自前の試行を重ねたとき、失敗が続くと上流が受ける回数（掛け算になる）。"""
    return (sdk_retries + 1) * own_attempts
