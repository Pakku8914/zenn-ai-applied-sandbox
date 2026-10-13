"""問題6：stop を受けたら、話している途中でもそこまでを1発話として確定させる（押して話す方式）。

    APP_MODULE=src.session10.solutions.q6_push_to_talk:app docker compose up -d --wait api
"""

from __future__ import annotations

import time

from fastapi import FastAPI, WebSocket

from src.session10.app import accept_voice, lifespan
from src.session10.latency import TurnTimes
from src.session10.session import VoiceSession
from src.session10.vad import UtteranceDetector, VadEvent


class PushToTalkDetector(UtteranceDetector):
    def finish(self) -> VadEvent | None:
        """話している途中なら、そこまでを1発話として切り出す。話していなければ None。"""
        if not self.in_speech:
            return None
        audio = b"".join(self._utt)      # 30ms に満たない端数（_buf）は捨てる
        self.reset()
        return VadEvent("speech_end", self.frame_index, audio)


class PushToTalkSession(VoiceSession):
    async def on_control(self, data: dict | None) -> bool:
        if data is not None and data.get("type") == "stop" and self.turn is None:
            event = self.detector.finish()
            if event is not None:
                now = time.perf_counter()
                await self.send({"type": "vad", "state": "speech_end"})
                self.start_turn(event.audio, TurnTimes(last_voice=self.last_voice_at, speech_end=now))
        return await super().on_control(data)    # 返答を最後まで送ってから閉じる処理は、元のまま使う


app = FastAPI(title="こんだてAI セッション10 問題6（押して話す）", lifespan=lifespan)


@app.websocket("/ws/voice")
async def voice(ws: WebSocket) -> None:
    if await accept_voice(ws):
        await PushToTalkSession(ws, ws.app.state, detector=PushToTalkDetector()).run()
