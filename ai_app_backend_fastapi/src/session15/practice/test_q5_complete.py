"""前半・練習問題5の解答のテスト：mockllm で録った complete() を再生する。呼び出しの種類も照合の対象にする。"""

from __future__ import annotations

from pathlib import Path

import pytest

from ..cassette import CassetteMismatch
from ..providers import Usage
from ..testkit import TEXT_REQ, mock_provider, mock_stats
from .q5_complete import RecordingProviderQ5, ReplayProviderQ5, complete_entry


@pytest.mark.usefixtures("mock")
async def test_complete_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "complete.jsonl"
    async with mock_provider() as inner:
        recorder = RecordingProviderQ5(inner)
        live = await recorder.complete(TEXT_REQ)
    recorder.save(path)

    replay = ReplayProviderQ5.load(path)
    again = await replay.complete(TEXT_REQ)
    assert (again.text, again.stop_reason, again.usage) == (live.text, live.stop_reason, live.usage)
    assert (len(again.text), again.usage) == (192, Usage(34, 181))
    assert again.request_id == "req_replay_000001"
    replay.assert_all_used()
    assert (await mock_stats())["total"] == 1  # 再生では mockllm を呼んでいない


async def test_call_kind_is_part_of_the_match() -> None:
    entry = complete_entry(TEXT_REQ, result={"text": "x", "tool_calls": [], "stop_reason": "end_turn",
                                             "usage": {"input_tokens": 1, "output_tokens": 1}})
    replay = ReplayProviderQ5([entry])
    with pytest.raises(CassetteMismatch, match="種類"):
        await anext(replay.stream(TEXT_REQ))  # complete で録ったものを stream で使おうとした
