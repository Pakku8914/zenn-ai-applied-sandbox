"""ウォームアップ（セッション14の warmup.py の写し）。終わるまでは GET /health/deps が 503 を返す。"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

import numpy as np

from kondate.settings import get_settings

WARMUP_TEXT = "こんにちは"
Warmer = Callable[[], Awaitable[None]]


class Warmup:
    def __init__(self, warmers: dict[str, Warmer]) -> None:
        self._warmers = warmers
        self.state = {name: "pending" for name in warmers}
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        for name, warm in self._warmers.items():
            self.state[name] = "running"
            try:
                await warm()
                self.state[name] = "ok"
            except Exception as e:
                self.state[name] = f"ng ({type(e).__name__})"

    @property
    def ready(self) -> bool:
        return all(v == "ok" for v in self.state.values())

    async def wait(self) -> None:
        if self._task is not None:
            await self._task

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


def default_warmers(state: Any, output_rate: int) -> dict[str, Warmer]:
    settings = get_settings()

    async def whisper() -> None:
        silence = np.zeros(settings.stt_sample_rate, dtype=np.float32)
        await state.stt_gate.run_sync(state.transcriber, silence, settings.stt_sample_rate)

    async def voicevox() -> None:
        await state.voicevox.ensure_user_dict()
        await state.tts_gate.run(state.voicevox.synthesize, WARMUP_TEXT, sample_rate=output_rate)

    return {"whisper": whisper, "voicevox": voicevox}
