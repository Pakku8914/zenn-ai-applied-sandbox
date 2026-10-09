"""練習問題4：イベントループを止めていた3つのルートを直したもの（(d) は元から問題ない）。"""

from __future__ import annotations

import asyncio
import time

import httpx2
from fastapi import APIRouter

from src.session02.deps import HttpDep, SettingsDep, StoreDep
from src.session02.errors import ApiError

router = APIRouter(tags=["q4"])

TIP = "鶏むね肉は片栗粉をまぶしてから焼くと、固くなりにくくなります"


@router.get("/api/recipes/count")
async def count_recipes(store: StoreDep) -> dict[str, int]:
    # (a) 毎回ファイルを同期で読まず、lifespan で読み込み済みのデータを使う
    return {"count": len(store.recipes)}


@router.get("/api/tips/slow")
async def slow_tip() -> dict[str, str]:
    # (b) 待つだけなら await asyncio.sleep。ループを手放すので同時に来た分も並行に進む
    await asyncio.sleep(0.3)
    return {"tip": TIP}


@router.get("/api/upstream")
async def upstream(http: HttpDep, settings: SettingsDep) -> dict[str, str]:
    # (c) urllib（同期 I/O）をやめ、lifespan の共有クライアントで await する
    try:
        r = await http.get(f"{settings.mockllm_url}/_mock/health")
        r.raise_for_status()
    except httpx2.HTTPError:
        raise ApiError(503, "upstream_unavailable", "AI が一時的に利用できません。時間をおいて再度お試しください。") from None
    return {"mockllm": "ok"}


@router.get("/api/tips/thread")
def thread_tip() -> dict[str, str]:
    # (d) def のルートはスレッドプールで動くので、同期の待ちがあってもループは止まらない
    time.sleep(0.3)
    return {"tip": TIP}
