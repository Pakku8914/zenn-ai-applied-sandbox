"""問題7：読み上げ中（speaking）だけ割り込みのしきい値を上げ、エコーや相づちで止まりにくくする。

    APP_MODULE=src.session11.solutions.q7_stateful_threshold:app docker compose up -d --wait api
"""

from __future__ import annotations

from fastapi import FastAPI, WebSocket

from src.session11.app import accept_voice, lifespan
from src.session11.session import VoiceSession
from src.session11.turns import TurnState
from src.session11.vad import FRAME_MS

SPEAKING_MS = 500


class StatefulThresholdSession(VoiceSession):
    def __init__(self, *args, speaking_ms: int = SPEAKING_MS, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.speaking_frames = speaking_ms // FRAME_MS

    def should_barge_in(self) -> bool:
        if self.machine.state == TurnState.SPEAKING:   # スピーカーが鳴っている間だけ厳しくする
            return self.detector.in_speech and self.detector.voiced_frames >= self.speaking_frames
        return super().should_barge_in()               # thinking は元のまま（300ms）


app = FastAPI(title="こんだてAI セッション11 問題7（状態でしきい値を変える）", lifespan=lifespan)


@app.websocket("/ws/voice")
async def voice(ws: WebSocket) -> None:
    if await accept_voice(ws):
        await StatefulThresholdSession(ws, ws.app.state, user_id=ws.headers.get("x-user-id", "u001")).run()
