"""前半・練習問題6の解答：録画のモード（replay / record / auto）を切り替えてプロバイダを用意する。

- replay：カセットを再生する。無ければ失敗（CI はこれ）
- record：mockllm から録り直し、抜けるときに保存する
- auto　：カセットがあれば再生、無ければ録画（手元で新しいテストを書くときだけ）
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from ..cassette import RecordingProvider, ReplayProvider
from ..providers import LLMProvider
from ..testkit import mock_provider

MODES = ("replay", "record", "auto")


@asynccontextmanager
async def cassette_provider(path: Path, mode: str = "replay") -> AsyncIterator[LLMProvider]:
    if mode not in MODES:
        raise ValueError(f"mode は {'・'.join(MODES)} のどれかです: {mode}")
    if mode == "auto":
        mode = "replay" if path.exists() else "record"
    if mode == "replay":
        if not path.exists():
            raise FileNotFoundError(f"カセットがありません: {path.name}（mode=record で mockllm から録画してください）")
        replay = ReplayProvider.load(path)
        yield replay
        replay.assert_all_used()  # 本体が成功したときだけ確かめる（失敗したらその例外を優先する）
        return
    async with mock_provider() as inner:  # 録画の接続先は必ず mockllm
        recorder = RecordingProvider(inner)
        yield recorder
    recorder.save(path)
