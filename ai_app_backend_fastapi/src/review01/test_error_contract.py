"""問題7の解答：上流の失敗が、どのプロバイダでも同じ HTTP 応答になることを確かめる契約テスト（3実装 × 5種類）。

本物の2つは mockllm に向け、障害注入ヘッダをクライアントの default_headers で送る。リトライは 0。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
import pytest

from kondate.settings import get_settings

from .app import ProviderFactory, create_app
from .providers import FakeProvider, LLMProvider, ProviderError, open_provider

PROVIDERS = ["anthropic", "openai", "fake"]
QUESTION = {"recipe_id": "R001", "question": "この料理に合う副菜を教えて"}
TIMEOUT = 1.0  # TTFT 2.5 秒の注入より短くして、タイムアウトを起こす

# 種類 → (本物に送るヘッダ, Fake が投げる ProviderError の (kind, status_code, retry_after), 期待する応答)
CASES: dict[str, tuple[dict[str, str], tuple[str, int | None, int | None], tuple[int, str, str | None]]] = {
    "429": ({"x-mock-fault": "429"}, ("rate_limited", 429, 1), (429, "rate_limited", "1")),
    "529": ({"x-mock-fault": "529"}, ("overloaded", 529, None), (503, "upstream_unavailable", None)),
    "500": ({"x-mock-fault": "500"}, ("server_error", 500, None), (503, "upstream_unavailable", None)),
    "timeout": ({"x-mock-ttft-ms": "2500"}, ("timeout", None, None), (504, "upstream_timeout", None)),
    "bad_request": ({"x-mock-scenario": "no_such_scenario"}, ("bad_request", 400, None),
                    (502, "upstream_error", None)),
}


def factory(name: str, case: str) -> ProviderFactory:
    headers, (kind, status, retry_after), _ = CASES[case]

    @asynccontextmanager
    async def open_llm() -> AsyncIterator[LLMProvider]:
        if name == "fake":
            yield FakeProvider([ProviderError(kind, provider="fake", status_code=status, retry_after=retry_after)])
            return
        s = get_settings()
        async with open_provider(
            name, model=s.llm_model,
            base_url=s.mockllm_url if name == "anthropic" else f"{s.mockllm_url}/v1",
            api_key="mock-key", max_retries=0, timeout=TIMEOUT, default_headers=headers,
        ) as provider:
            yield provider

    return open_llm


@pytest.mark.parametrize("case", list(CASES))
@pytest.mark.parametrize("name", PROVIDERS)
async def test_upstream_failure_has_same_http_shape(name: str, case: str) -> None:
    app = create_app(factory(name, case))
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=10) as c:
            r = await c.post("/api/suggest", json=QUESTION)
    err = r.json()["error"]
    assert (r.status_code, err["type"], r.headers.get("retry-after")) == CASES[case][2]
    assert err["request_id"] == r.headers["x-request-id"]
    assert "mockllm" not in r.text and "req_mock_" not in r.text  # 上流の文と上流の ID を漏らさない
