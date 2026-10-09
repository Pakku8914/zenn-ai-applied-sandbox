"""前半・練習問題6の解答のテスト：replay はカセットが無ければ止まり、auto は1回だけ録って以後は再生する。"""

from __future__ import annotations

from pathlib import Path

import pytest

from ..cassette import load_cassette
from ..providers import Usage, accumulate
from ..testkit import TEXT_REQ, mock_stats
from .cassette_mode import cassette_provider


async def test_replay_mode_without_cassette_fails(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="mode=record"):
        async with cassette_provider(tmp_path / "missing.jsonl"):
            pass


@pytest.mark.usefixtures("mock")
async def test_auto_records_once_then_replays(tmp_path: Path) -> None:
    path = tmp_path / "auto.jsonl"
    for _ in range(2):  # 1回目は録画、2回目は再生
        async with cassette_provider(path, "auto") as provider:
            events = [ev async for ev in provider.stream(TEXT_REQ)]
        assert accumulate(events).usage == Usage(34, 181)
    assert len(load_cassette(path)) == 1
    assert (await mock_stats())["total"] == 1  # 2回目は mockllm を呼んでいない
