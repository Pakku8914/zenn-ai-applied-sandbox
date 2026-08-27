"""推論サーバの前段に置くゲートウェイ（セッション5の参照実装）。

責務：レート制限・バックプレッシャ・キャッシュ・観測。
推論そのものは llama.cpp に任せ、ここでは「守る」ことだけをする。
"""

from __future__ import annotations

import os
import time
from collections import deque

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from infrakit.cache import ExactCache
from infrakit.client import LlamaClient

app = FastAPI(title="みなと商事 推論ゲートウェイ")
client = LlamaClient()
cache = ExactCache(ttl_seconds=float(os.environ.get("CACHE_TTL", "300")))

RATE_LIMIT_RPS = float(os.environ.get("RATE_LIMIT_RPS", "2"))
RATE_LIMIT_BURST = float(os.environ.get("RATE_LIMIT_BURST", "4"))
MAX_INFLIGHT = int(os.environ.get("MAX_INFLIGHT", "4"))


class TokenBucket:
    """トークンバケットによるレート制限。

    毎秒 rate 個のトークンが補充され、リクエストは1個消費する。
    burst まで貯められるので、瞬間的な集中は吸収できる。
    """

    def __init__(self, rate: float, burst: float) -> None:
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.updated = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


bucket = TokenBucket(RATE_LIMIT_RPS, RATE_LIMIT_BURST)
inflight: deque[float] = deque()
stats = {"requests": 0, "rate_limited": 0, "rejected": 0, "cache_hits": 0, "errors": 0}


class GenRequest(BaseModel):
    prompt: str
    max_tokens: int = 64
    use_cache: bool = True


@app.get("/healthz")
def healthz() -> dict:
    """ゲートウェイ自身の生存確認。推論サーバの状態とは分けて返す。"""
    return {"ok": True, "upstream_healthy": client.health()}


@app.get("/stats")
def get_stats() -> dict:
    return {**stats, "inflight": len(inflight),
            "cache": {"hits": cache.stats.hits, "misses": cache.stats.misses,
                      "hit_rate": round(cache.stats.hit_rate, 3)}}


@app.post("/generate")
def generate(req: GenRequest) -> dict:
    stats["requests"] += 1

    if not bucket.allow():
        stats["rate_limited"] += 1
        # 429 は「あなたが速すぎる」。クライアントは待って再送してよい
        raise HTTPException(status_code=429, detail="レート制限を超えました。少し待って再送してください。")

    if len(inflight) >= MAX_INFLIGHT:
        stats["rejected"] += 1
        # 503 は「こちらが手一杯」。キューに積まずに断るのがバックプレッシャ
        raise HTTPException(status_code=503, detail="処理中のリクエストが上限に達しています。")

    if req.use_cache:
        cached = cache.get(req.prompt)
        if cached is not None:
            stats["cache_hits"] += 1
            return {"text": cached, "cached": True}

    inflight.append(time.monotonic())
    try:
        result = client.generate(req.prompt, max_tokens=req.max_tokens)
    finally:
        inflight.popleft()

    if not result.ok:
        stats["errors"] += 1
        raise HTTPException(status_code=502, detail=result.error or "推論に失敗しました")

    if req.use_cache:
        cache.put(req.prompt, result.text, result.total_ms)
    return {"text": result.text, "cached": False,
            "ttft_ms": round(result.ttft_ms, 1), "total_ms": round(result.total_ms, 1),
            "tokens_out": result.tokens_out}
