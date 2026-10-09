"""イベントループを止める書き方・止めない書き方を並べた実験用のルート。"""

from __future__ import annotations

import asyncio
import time

import anyio
from fastapi import APIRouter

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("/sleep/blocking")
async def sleep_blocking() -> dict[str, str]:
    time.sleep(0.2)  # NG：async def の中の同期待ち。待っている間、ほかのリクエストも止まる
    return {"mode": "blocking"}


@router.get("/sleep/async")
async def sleep_async() -> dict[str, str]:
    await asyncio.sleep(0.2)  # OK：待つ間はイベントループを手放す
    return {"mode": "async"}


@router.get("/sleep/thread")
def sleep_thread() -> dict[str, str]:
    time.sleep(0.2)  # OK：def のルートは FastAPI がスレッドプールで動かす
    return {"mode": "thread"}


@router.get("/sleep/offload")
async def sleep_offload() -> dict[str, str]:
    await anyio.to_thread.run_sync(time.sleep, 0.2)  # OK：同期処理だけをスレッドへ逃がす
    return {"mode": "offload"}
