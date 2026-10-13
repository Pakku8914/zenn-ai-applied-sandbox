"""セッション10：リアルタイム音声対話。

- GET  /health    … 生存確認
- GET  /          … 音声対話の1ページ（static/voice.html。ビルド工程なし）
- WS   /ws/voice  … API契約⑤（マイクの PCM → VAD → 音声認識 → LLM のストリーミング → 文ごとの音声合成）

    APP_MODULE=src.session10.app:app docker compose up -d --wait api
    ブラウザで http://localhost:8720/ を開く（マイクは https か localhost のページでしか使えない）
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from anthropic import AsyncAnthropic
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from kondate import stt
from kondate.llm import AnthropicProvider
from kondate.tts import Voicevox
from kondate.usage import UsageLog
from src.session10.session import POLICY_VIOLATION, VoiceSession

STATIC = Path(__file__).parent / "static"
# ブラウザは、別のサイトのページからでも WebSocket をつなげる（CORS の対象外）。画面を配る自分のオリジンだけを受け付ける
ALLOWED_ORIGINS = {"http://localhost:8720", "http://127.0.0.1:8720"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = AsyncAnthropic()                        # 接続先とキーは環境変数 ANTHROPIC_BASE_URL・ANTHROPIC_API_KEY から読む
    app.state.llm = AnthropicProvider(client)
    app.state.voicevox = Voicevox()
    app.state.usage = UsageLog()
    app.state.stt_limiter = anyio.CapacityLimiter(1)  # 認識は同時に1件（セッション8と同じ）
    app.state.transcriber = stt.transcribe           # 検証で差し替えられるよう state に置く
    yield
    await app.state.voicevox.aclose()
    await client.close()


app = FastAPI(title="こんだてAI セッション10", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "voice.html", media_type="text/html; charset=utf-8")


async def accept_voice(ws: WebSocket) -> bool:
    """Origin を確かめてから接続を受け付ける。Origin の無い接続（ブラウザ以外のクライアント）は受け付ける。"""
    origin = ws.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        await ws.close(code=POLICY_VIOLATION)        # accept の前に閉じると、ハンドシェイクが 403 で断られる
        return False
    await ws.accept()
    return True


@app.websocket("/ws/voice")
async def voice(ws: WebSocket) -> None:
    if await accept_voice(ws):
        await VoiceSession(ws, ws.app.state, user_id=ws.headers.get("x-user-id", "u001")).run()
