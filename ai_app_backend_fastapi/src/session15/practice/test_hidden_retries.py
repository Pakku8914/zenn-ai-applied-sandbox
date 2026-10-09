"""後半・練習問題5の解答：SDK の自動リトライは、応答だけでは見えない。mockllm の統計で数える。"""

from __future__ import annotations

from uuid import uuid4

import anthropic
import pytest

from kondate.settings import get_settings

from ..providers import AnthropicProvider
from ..store import MemoryStore
from ..testkit import chat_once, mock_stats

pytestmark = pytest.mark.usefixtures("mock")


async def test_sdk_retries_are_visible_only_in_stats(memory_store: MemoryStore) -> None:
    s = get_settings()
    key = f"s15-retries-{uuid4().hex[:8]}"
    headers = {"x-mock-fault": "529", "x-mock-fault-times": "2", "x-mock-fault-key": key}
    # わざと SDK の既定（max_retries=2）のままにしたクライアント
    client = anthropic.AsyncAnthropic(base_url=s.mockllm_url, api_key="mock-key", max_retries=2, timeout=10.0,
                                      default_headers=headers)
    try:
        run = await chat_once(AnthropicProvider(client, default_model=s.llm_model), memory_store)
    finally:
        await client.close()
    assert run.shape() == "start → delta×32 → usage → done"  # 利用者からは、ただの成功に見える
    stats = await mock_stats()
    assert stats["by_status"] == {"529": 2, "200": 1}  # 実際には上流を3回呼んでいた
    assert stats["faults"][key]["retry_counts"] == ["0", "1", "2"]  # SDK が付けた x-stainless-retry-count
