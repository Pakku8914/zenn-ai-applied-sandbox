"""nginx を通したときのバッファリングを測る（verify-all.sh には含めない。nginx を起動してから手で実行する）。

    APP_MODULE=src.session06.app:app docker compose up -d --wait api
    docker compose --profile proxy up -d nginx
    docker compose exec api python src/session06/proxy_check.py

api コンテナの中から、nginx（compose 内の名前 nginx・80 番）と、自分自身（127.0.0.1:8000）の両方を呼んで比べる。
"""

from __future__ import annotations

import time

import httpx2

from kondate.verifykit import check, finish, sse_events

NGINX = "http://nginx"
DIRECT = "http://127.0.0.1:8000"
PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"


async def arrivals(method: str, url: str, body: dict | None = None) -> tuple[list[float], list[str | None], dict]:
    """ブロックごとの到着時刻（秒）とイベント名、応答ヘッダを返す。"""
    at: list[float] = []
    names: list[str | None] = []
    lines: list[str] = []
    started = time.perf_counter()
    async with httpx2.AsyncClient(timeout=60) as c, c.stream(method, url, json=body) as r:
        assert r.status_code == 200, r.status_code
        async for line in r.aiter_lines():
            if line != "":
                lines.append(line)
                continue
            for ev in sse_events([*lines, ""]):
                at.append(time.perf_counter() - started)
                names.append(ev["event"])
            lines = []
        return at, names, dict(r.headers)


@check("P1 直接つなぐと、tick は 0.3 秒おきに1個ずつ届く")
async def _():
    at, _, _ = await arrivals("GET", f"{DIRECT}/api/s06/ticks")
    assert len(at) == 5 and at[0] < 0.5 and at[-1] - at[0] >= 1.0, at
    return "最初の tick は 0.5 秒未満・最後まで 1.0 秒以上かけて届く"


@check("P2 nginx 経由・ヘッダなし：tick は最後にまとめて届く（バッファリング）")
async def _():
    at, _, _ = await arrivals("GET", f"{NGINX}/api/s06/ticks")
    assert len(at) == 5 and at[0] >= 1.0 and at[-1] - at[0] < 0.2, at
    return "最初の tick が届くのは 1.0 秒以上あと・5個がほぼ同時に届く"


@check("P3 nginx 経由・X-Accel-Buffering: no：直接と同じく1個ずつ届き、ヘッダはクライアントに渡らない")
async def _():
    at, _, headers = await arrivals("GET", f"{NGINX}/api/s06/ticks?fix=1")
    assert len(at) == 5 and at[0] < 0.5 and at[-1] - at[0] >= 1.0, at
    assert "x-accel-buffering" not in headers, headers
    return "最初の tick は 0.5 秒未満・nginx は X-Accel-* ヘッダを取り除いて返す"


@check("P4 nginx 経由の POST /api/chat/stream：fastapi.sse がヘッダを付けるので、ためられない")
async def _():
    at, names, _ = await arrivals("POST", f"{NGINX}/api/chat/stream", {"message": PROMPT})
    assert names[0] == "start" and names[-1] == "done", names
    assert at[-1] - at[0] >= 1.0, at  # mockllm の既定の遅延（40 tokens/s）で、done まで数秒かかる
    return "start から done まで 1.0 秒以上かけて少しずつ届く"


finish("session06-proxy")
