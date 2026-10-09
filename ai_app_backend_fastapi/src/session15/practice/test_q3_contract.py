"""後半・練習問題1の解答のテスト：正しいストリームは合格し、壊れた並びは理由つきで不合格になる。"""

from __future__ import annotations

import json

import pytest

from ..providers import FakeProvider, ProviderError, TextDelta, Usage, fake_script
from ..store import MemoryStore
from ..testkit import FAKE_ANSWER, chat_once
from .q3_contract import assert_sse_contract, contract_violations


@pytest.mark.parametrize("script", [
    fake_script(FAKE_ANSWER, usage=Usage(34, 20)),
    [TextDelta("鶏むね肉とキ"), ProviderError("timeout", provider="fake")],
], ids=["done", "error"])
async def test_app_streams_follow_the_contract(script: list, memory_store: MemoryStore) -> None:
    run = await chat_once(FakeProvider(script), memory_store, stop_at_terminal=False)
    assert_sse_contract(run)


def test_broken_stream_is_rejected_with_reasons() -> None:
    names = ["start", "delta", "done"]  # usage を飛ばした
    data_lines = [json.dumps({"message_id": "m1"}), json.dumps({"text": "鶏むね肉"}),  # 既定の ensure_ascii=True
                  json.dumps({"stop_reason": "end_turn"})]
    assert contract_violations(names, data_lines) == ["done の直前が usage ではない", "日本語がエスケープされている"]
