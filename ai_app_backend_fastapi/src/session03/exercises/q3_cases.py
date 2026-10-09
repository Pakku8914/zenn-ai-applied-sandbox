"""問題3の解答：SDK が実際に投げる例外を mockllm から集め、翻訳関数を FastAPI 抜きで確かめる。"""

from __future__ import annotations

import anthropic
from anthropic import AsyncAnthropic

QUESTION = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"

CASES: dict[str, dict[str, str]] = {
    "429": {"x-mock-fault": "429"},
    "500": {"x-mock-fault": "500"},
    "529": {"x-mock-fault": "529"},
    "400": {"x-mock-scenario": "no_such_scenario"},
    "timeout": {"x-mock-ttft-ms": "1000"},
}


async def collect_errors(base_url: str, model: str) -> dict[str, anthropic.APIError]:
    llm = AsyncAnthropic(api_key="mock-key", base_url=base_url, max_retries=0)
    down = AsyncAnthropic(api_key="mock-key", base_url=base_url.rsplit(":", 1)[0] + ":9", max_retries=0)
    errors: dict[str, anthropic.APIError] = {}
    try:
        for name, headers in CASES.items():
            client = llm.with_options(timeout=0.3) if name == "timeout" else llm
            try:
                await client.messages.create(model=model, max_tokens=16, extra_headers=headers,
                                             messages=[{"role": "user", "content": QUESTION}])
            except anthropic.APIError as exc:
                errors[name] = exc
        try:
            await down.messages.create(model=model, max_tokens=16,
                                       messages=[{"role": "user", "content": QUESTION}])
        except anthropic.APIError as exc:
            errors["connect"] = exc
    finally:
        await llm.close()
        await down.close()
    return errors
