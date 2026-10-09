"""練習問題4の解答：「max_tokens で打ち切られた」も3実装で同じ形になる、という契約テスト。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from .contract_kit import PROVIDERS, TEXT_REQ, provider_under_test
from .providers import Usage, accumulate, fake_script

FAKE_CUT = fake_script("鶏むね肉とキャベツが", stop_reason="max_tokens", usage=Usage(34, 10))
contract = pytest.mark.parametrize("name", PROVIDERS)


@contract
async def test_max_tokens_is_normalized(name: str) -> None:
    req = replace(TEXT_REQ, max_tokens=10)
    async with provider_under_test(name, FAKE_CUT) as p:
        result = await p.complete(req)
        events = [ev async for ev in p.stream(req)]
    assert result.stop_reason == "max_tokens"
    assert 0 < result.usage.output_tokens <= req.max_tokens
    assert accumulate(events) == replace(result, request_id=None)
