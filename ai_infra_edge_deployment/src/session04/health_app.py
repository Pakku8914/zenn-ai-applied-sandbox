#!/usr/bin/env python3
"""ヘルスチェックを HTTP エンドポイントとして公開する（セッション4）。

起動・準備完了・生存を**別々のパス**に分ける。監視側は本文（JSON）を読まず、
ステータスコードだけで判定できるようにする。

起動:
    docker compose exec -d app uvicorn src.session04.health_app:app \
        --host 0.0.0.0 --port 8001
確認:
    docker compose exec app python -c "import httpx; \
        print(httpx.get('http://localhost:8001/statusz').json())"
"""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from infrakit.client import LlamaClient
from src.session04.readiness import Probe, ReadinessGate, run_startup

gate = ReadinessGate(warmup_required=2)


def probe_response(probe: Probe) -> JSONResponse:
    """成功は 200、そうでなければ 503 を返す。

    レート制限の 429 と過負荷時の 503 の使い分けはゲートウェイ側の話題で、
    セッション5で扱う。ここでは「まだ受けられない」を 503 で表すだけ。
    """
    return JSONResponse(status_code=200 if probe.ok else 503,
                        content={"ok": probe.ok, "phase": probe.phase, **probe.detail})


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 起動シーケンスは別スレッドで進める。ロードを待つ間もエンドポイントは応答する
    # （応答できなければ「生存」を報告できず、殺されてしまう）
    threading.Thread(target=run_startup,
                     args=(gate, LlamaClient()),
                     kwargs={"warmups": gate.warmup_required},
                     daemon=True).start()
    yield
    gate.begin_drain()


app = FastAPI(title="みなと商事 推論サービングのヘルスチェック", lifespan=lifespan)


@app.get("/startupz")
def startupz() -> JSONResponse:
    """起動：モデルのロードが終わったか。ここが通るまで時間がかかる。"""
    return probe_response(gate.startup())


@app.get("/readyz")
def readyz() -> JSONResponse:
    """準備完了：いま受け付けてよいか。ロード中・ウォームアップ中は 503。"""
    return probe_response(gate.ready())


@app.get("/livez")
def livez() -> JSONResponse:
    """生存：プロセスが壊れていないか。ロード中でも 200 を返す。"""
    return probe_response(gate.live())


@app.get("/statusz")
def statusz() -> dict:
    """人が見る用。3種の判定と進み具合をまとめて返す。"""
    return gate.snapshot()
