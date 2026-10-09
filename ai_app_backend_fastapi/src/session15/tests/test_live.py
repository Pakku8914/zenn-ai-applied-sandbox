"""実 API の任意確認（課金あり）。既定では skip。RUN_LIVE=1 と本物の ANTHROPIC_API_KEY があるときだけ動く。

    docker compose exec -e RUN_LIVE=1 api python -m pytest src/session15/tests -m live -p no:cacheprovider

確かめるのは「契約（イベントの並びと usage の有無）」だけ。応答の文面は毎回変わるので比べない。
"""

from __future__ import annotations

import os

import pytest

from kondate.settings import get_settings

from ..providers import ChatRequest, Done, TextDelta, open_provider

LIVE_ENABLED = os.environ.get("RUN_LIVE") == "1" and os.environ.get("ANTHROPIC_API_KEY", "mock-key") != "mock-key"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not LIVE_ENABLED, reason="実 API の確認は RUN_LIVE=1 と本物の ANTHROPIC_API_KEY があるときだけ（課金あり）"),
]


async def test_live_stream_contract() -> None:
    req = ChatRequest(messages=[{"role": "user", "content": "「こんにちは」とだけ返してください。"}], max_tokens=16)
    async with open_provider("anthropic", model=get_settings().llm_model_light, base_url="https://api.anthropic.com",
                             max_retries=0, timeout=30.0) as provider:
        events = [ev async for ev in provider.stream(req)]
    assert isinstance(events[-1], Done)
    assert events[-1].usage.input_tokens > 0
    assert any(isinstance(ev, TextDelta) for ev in events)
