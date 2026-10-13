"""問題6：音声を返す応答に、クレジットのヘッダを付け忘れない仕組み。

音声（content-type が audio/ で始まる）を返す応答にヘッダが無ければ、ミドルウェアが付ける。
"""

from __future__ import annotations

from urllib.parse import quote

import numpy as np
from fastapi import FastAPI
from fastapi.responses import Response

from kondate.audio import float32_to_wav
from kondate.settings import get_settings


def add_credit_guard(app: FastAPI, credit: str) -> None:
    header = quote(credit, safe=":")

    @app.middleware("http")
    async def credit_guard(request, call_next):
        response = await call_next(request)
        if response.headers.get("content-type", "").startswith("audio/") and "x-voice-credit" not in response.headers:
            response.headers["x-voice-credit"] = header
        return response


demo = FastAPI(title="クレジットの付け忘れ防止（問題6）")
add_credit_guard(demo, get_settings().voicevox_credit)


@demo.get("/api/voice/silence")
async def silence() -> Response:
    """わざとヘッダを付け忘れた、音声を返すエンドポイント（0.5 秒の無音）。"""
    return Response(float32_to_wav(np.zeros(12000, np.float32), 24000), media_type="audio/wav")


@demo.get("/api/hello")
async def hello() -> dict:
    return {"message": "こんにちは"}
