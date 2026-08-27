#!/usr/bin/env python3
"""キャッシュキーに権限を含めるゲートウェイ（セッション6）。

`gateway/main.py`（セッション5の参照実装）は `ExactCache` を使っており、
鍵にテナントも可視範囲も入っていない。ここではその欠けを塞いだ版を作る。

上流の推論は差し替えられるようにしてある（`create_app(generate=...)`）。
おかげで推論サーバを起動しなくても、キャッシュの境界だけをテストできる。

単体で動かす場合（既定の 8000 番はセッション5のゲートウェイが使うので 8001 にする）:

    docker compose exec app uvicorn src.session06.safe_gateway:app --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI, Header, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from src.session06.cache_keys import CacheScope, ScopedCache  # noqa: E402

# ロール → 参照してよい資料の範囲。可視範囲の定義はここ1か所にまとめる
ROLE_VISIBILITY: dict[str, set[str]] = {
    "employee": {"general"},
    "hr": {"general", "hr-confidential"},
    "it": {"general", "it-internal"},
}

CORPUS_VERSION = os.environ.get("CORPUS_VERSION", "2026-08-15")
MODEL_FILE = os.environ.get("MODEL_FILE", "qwen05b-q4_k_m.gguf")
# 1件あたりの推論時間の概算（Q8_0・並列1 の総時間 p50 = 730ms・2026-08-15 実測）
COST_MS = 730.0


class GenRequest(BaseModel):
    prompt: str
    max_tokens: int = 64
    temperature: float = 0.0


def visibility_of(roles: str) -> frozenset[str]:
    """ロールの一覧（カンマ区切り）から可視範囲を求める。未知のロールは無視する。"""
    granted: set[str] = set()
    for role in (r.strip() for r in roles.split(",")):
        granted |= ROLE_VISIBILITY.get(role, set())
    return frozenset(granted or {"general"})


def default_generate(prompt: str, max_tokens: int, temperature: float) -> str:
    """既定の上流。推論サーバを呼ぶ。"""
    from infrakit.client import LlamaClient

    result = LlamaClient().generate(prompt, max_tokens=max_tokens, temperature=temperature)
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.error or "推論に失敗しました")
    return result.text


def create_app(generate: Callable[[str, int, float], str] | None = None,
               cache: ScopedCache | None = None) -> FastAPI:
    app = FastAPI(title="みなと商事 推論ゲートウェイ（キャッシュキーに権限を含める）")
    upstream = generate or default_generate
    store = cache if cache is not None else ScopedCache(
        ttl_seconds=float(os.environ.get("CACHE_TTL", "300")))
    app.state.cache = store

    @app.post("/generate")
    def generate_endpoint(req: GenRequest,
                          x_tenant_id: str | None = Header(default=None),
                          x_roles: str = Header(default="employee")) -> dict:
        if not x_tenant_id:
            # 誰の質問か分からないものは受けない。分からないまま鍵を作るのが事故のもと
            raise HTTPException(status_code=400, detail="X-Tenant-Id ヘッダが必要です。")

        scope = CacheScope(tenant_id=x_tenant_id,
                           visibility=visibility_of(x_roles),
                           model=MODEL_FILE,
                           max_tokens=req.max_tokens,
                           temperature=req.temperature,
                           corpus_version=CORPUS_VERSION)

        cached = store.get(scope, req.prompt)
        if cached is not None:
            return {"text": cached, "cached": True, "scope": scope.fingerprint()}

        text = upstream(req.prompt, req.max_tokens, req.temperature)
        store.put(scope, req.prompt, text, cost_ms=COST_MS)
        return {"text": text, "cached": False, "scope": scope.fingerprint()}

    @app.get("/cache/stats")
    def cache_stats() -> dict:
        return {"hits": store.stats.hits,
                "misses": store.stats.misses,
                "hit_rate": round(store.stats.hit_rate, 3),
                "saved_ms": round(store.stats.saved_ms, 1),
                "skipped": store.skipped,
                "keys": len(store.store)}

    @app.post("/cache/invalidate")
    def invalidate(tenant_id: str | None = None) -> dict:
        """消せるようにしておく。消せないキャッシュは事故のときに手が出せない。"""
        removed = (store.invalidate_tenant(tenant_id) if tenant_id
                   else store.invalidate_all())
        return {"removed": removed, "tenant_id": tenant_id}

    return app


app = create_app()
