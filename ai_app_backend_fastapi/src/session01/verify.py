"""環境構築の章の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session01
"""

from __future__ import annotations

import importlib.metadata as md
import math
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx2

from kondate.cache import make_redis
from kondate.data import EXPECTED_SHA12, data_path, load_recipes, load_users, sha12
from kondate.db import server_version
from kondate.settings import get_settings
from kondate.verifykit import check, eq, finish, sse_events
from kondate.worker import ping

API = get_settings().api_base_url
HELLO_PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"

# requirements.md「固定バージョン表」と一致していること（陳腐化の検知）
PINNED = {
    "fastapi": "0.142.2", "starlette": "1.7.0", "uvicorn": "0.54.0", "pydantic": "2.13.5",
    "pydantic-settings": "2.15.0", "anthropic": "1.11.0", "openai": "3.23.0", "httpx2": "2.13.1",
    "sqlalchemy": "2.1.1", "asyncpg": "0.31.0", "alembic": "1.20.0", "redis": "6.4.0",
    "celery": "5.6.3", "kombu": "5.6.2", "pytest": "9.1.1", "pytest-asyncio": "1.4.0",
}


@check("E1 Python とライブラリが固定バージョンどおり")
def _():
    eq(platform.python_version(), "3.12.14", "Python")
    eq({k: md.version(k) for k in PINNED}, PINNED, "ライブラリ")
    return f"Python {platform.python_version()}・{len(PINNED)} パッケージ"


@check("E2 共通データの SHA256 が契約どおりで、make_data.py で再生成しても一致する")
def _():
    eq({n: sha12(data_path(n)) for n in EXPECTED_SHA12}, EXPECTED_SHA12, "data/ のハッシュ")
    with tempfile.TemporaryDirectory() as d:
        subprocess.run([sys.executable, "tools/make_data.py", "--out", d], check=True, capture_output=True)
        eq({n: sha12(Path(d) / n) for n in EXPECTED_SHA12}, EXPECTED_SHA12, "再生成したハッシュ")
    recipes, users = load_recipes(), load_users()
    eq((len(recipes), len(users)), (120, 5), "件数")
    eq((recipes[0]["id"], recipes[0]["name"]), ("R001", "鶏むね肉とキャベツの塩炒め"), "R001")
    return f"recipes.json={EXPECTED_SHA12['recipes.json']} users.json={EXPECTED_SHA12['users.json']}"


@check("E3 GET /health が 200 を返す")
def _():
    r = httpx2.get(f"{API}/health", timeout=5)
    eq(r.status_code, 200, "status")
    eq(r.json(), {"status": "ok", "version": "0.1.0"}, "本文")
    return r.text


@check("E4 GET /health/deps で PostgreSQL・Redis・worker・mockllm がすべて ok")
def _():
    r = httpx2.get(f"{API}/health/deps", timeout=10)
    eq(r.status_code, 200, f"status（本文 {r.text}）")
    deps = r.json()["deps"]
    eq(sorted(deps), ["mockllm", "postgres", "redis", "worker"], "項目")
    return ", ".join(f"{k}={v}" for k, v in deps.items())


@check("E5 POST /api/hello/stream が mockllm 経由の応答を SSE で逐次返す")
def _():
    with httpx2.stream("POST", f"{API}/api/hello/stream", timeout=30) as r:
        eq(r.status_code, 200, "status")
        eq(r.headers["content-type"].split(";")[0], "text/event-stream", "content-type")
        eq(r.headers.get("x-accel-buffering"), "no", "x-accel-buffering")
        events = sse_events(r.iter_lines())
    names = [e["event"] for e in events]
    eq(names[-1], "done", "最後のイベント")
    deltas = [e["data"]["text"] for e in events if e["event"] == "delta"]
    eq(len(deltas), names.count("delta"), "delta の数")
    text = "".join(deltas)
    assert text.startswith("鶏むね肉とキャベツがあるなら"), text[:30]
    usage = events[-1]["data"]["usage"]
    expected_in = 4 + 3 + math.ceil(len(HELLO_PROMPT.encode()) / 3)
    eq(usage["input_tokens"], expected_in, "input_tokens（mockllm の式：4 + 3 + ceil(バイト数/3)）")
    eq(usage["output_tokens"], math.ceil(len(text.encode()) / 3), "output_tokens")
    eq(events[-1]["data"]["stop_reason"], "end_turn", "stop_reason")
    return f"delta {len(deltas)} 個・{len(text)} 字・input_tokens={usage['input_tokens']} output_tokens={usage['output_tokens']}"


@check("E6 PostgreSQL に SQLAlchemy（asyncpg）で接続できる")
async def _():
    version = await server_version()
    assert version.startswith("18."), version
    return f"server_version={version}"


@check("E7 Redis に書いて読める（キーは s01: で始める）")
async def _():
    redis = make_redis()
    try:
        await redis.set("s01:hello", "こんだて", ex=60)
        eq(await redis.get("s01:hello"), "こんだて", "GET")
        ttl = await redis.ttl("s01:hello")
        assert 0 < ttl <= 60, ttl
        await redis.delete("s01:hello")
        info = await redis.info("server")
    finally:
        await redis.aclose()
    return f"redis_version={info['redis_version']}"


@check("E8 Celery worker にジョブを投げて結果が返る")
def _():
    started = time.monotonic()
    result = ping.delay()
    eq(result.get(timeout=15), "pong", "kondate.ping の結果")
    assert time.monotonic() - started < 15
    return "kondate.ping → pong"


finish("session01")
