"""ウォームアップ：起動直後の「最初の1回だけ遅い」を、利用者が来る前に済ませる。

lifespan で start() し、終わるまでは GET /health/deps（readiness）が 503 を返す。GET /health（生存確認）は
ウォームアップの間も 200 を返す（「生きているが、まだ受け付ける準備ができていない」を区別するため）。
"""

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
        self.state = {name: "pending" for name in warmers}  # pending → running → ok / ng (例外の種類)
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        for name, warm in self._warmers.items():  # 1つずつ。同時に走らせると CPU を取り合い、どれも遅くなる
            self.state[name] = "running"
            try:
                await warm()
                self.state[name] = "ok"
            except Exception as e:  # 失敗の種類だけを残し、readiness で「準備ができていない」と知らせる
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
    """本物のウォームアップ。Whisper はモデルの読み込み＋1回の認識、VOICEVOX は辞書の登録＋1回の合成。"""
    settings = get_settings()

    async def whisper() -> None:
        silence = np.zeros(settings.stt_sample_rate, dtype=np.float32)  # 1秒の無音
        await state.stt_gate.run_sync(state.transcriber, silence, settings.stt_sample_rate)

    async def voicevox() -> None:
        await state.voicevox.ensure_user_dict()
        await state.tts_gate.run(state.voicevox.synthesize, WARMUP_TEXT, sample_rate=output_rate)

    return {"whisper": whisper, "voicevox": voicevox}
