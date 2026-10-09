"""環境構築の章で動かす最小のアプリ。

- GET  /health             … 生存確認（依存先は見ない）
- GET  /health/deps        … PostgreSQL・Redis・Celery worker・mockllm への疎通
- POST /api/hello/stream   … mockllm（Anthropic 互換）にストリーミングで問い合わせ、SSE でそのまま返す
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import httpx2
from anthropic import AsyncAnthropic
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent

from kondate import __version__
from kondate.cache import make_redis
from kondate.db import engine, server_version
from kondate.settings import get_settings
from kondate.worker import app as celery_app

HELLO_PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"

settings = get_settings()
llm = AsyncAnthropic()  # 接続先とキーは環境変数 ANTHROPIC_BASE_URL・ANTHROPIC_API_KEY から読む


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await llm.close()
    await engine.dispose()


app = FastAPI(title="こんだてAI バックエンド", version=__version__, lifespan=lifespan)


def event(name: str, payload: dict) -> ServerSentEvent:
    # data= に dict を渡すと json.dumps の既定（ensure_ascii=True）で日本語が \uXXXX になるため、自分で直列化する
    return ServerSentEvent(event=name, raw_data=json.dumps(payload, ensure_ascii=False))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/health/deps")
async def health_deps() -> JSONResponse:
    results: dict[str, str] = {}
    try:
        results["postgres"] = f"ok ({await server_version()})"
    except Exception as e:  # 疎通確認なので種類を問わず NG として返す
        results["postgres"] = f"ng ({type(e).__name__})"
    redis = make_redis()
    try:
        results["redis"] = "ok" if await redis.ping() else "ng"
    except Exception as e:
        results["redis"] = f"ng ({type(e).__name__})"
    finally:
        await redis.aclose()
    try:
        replies = await anyio.to_thread.run_sync(lambda: celery_app.control.ping(timeout=1.0))
        results["worker"] = f"ok ({len(replies)} 台)" if replies else "ng (応答なし)"
    except Exception as e:
        results["worker"] = f"ng ({type(e).__name__})"
    try:
        async with httpx2.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{settings.mockllm_url}/_mock/health")
        results["mockllm"] = f"ok ({r.json()['version']})" if r.status_code == 200 else f"ng ({r.status_code})"
    except Exception as e:
        results["mockllm"] = f"ng ({type(e).__name__})"
    ok = all(v.startswith("ok") for v in results.values())
    return JSONResponse({"status": "ok" if ok else "ng", "deps": results}, status_code=200 if ok else 503)


@app.post("/api/hello/stream", response_class=EventSourceResponse)
async def hello_stream() -> AsyncIterator[ServerSentEvent]:
    try:
        async with llm.messages.stream(
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            messages=[{"role": "user", "content": HELLO_PROMPT}],
        ) as stream:
            async for text in stream.text_stream:
                yield event("delta", {"text": text})
            final = await stream.get_final_message()
    except Exception:
        # 上流の生のエラー文はクライアントに出さない（詳しくはストリーミングの異常系のセッションで扱う）
        yield event("error", {"message": "LLM の呼び出しに失敗しました"})
        return
    yield event("done", {
        "stop_reason": final.stop_reason,
        "usage": {"input_tokens": final.usage.input_tokens, "output_tokens": final.usage.output_tokens},
    })
