"""練習問題4の解答：SSE を受けながら、start・最初の delta（TTFT）・done までの時間を測る。

    docker compose exec api python -m src.session05.q4_measure
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx2

from kondate.verifykit import sse_events


@dataclass(frozen=True)
class Measurement:
    start_s: float  # 送ってから start を受け取るまで（受け付けの速さ）
    ttft_s: float | None  # 送ってから最初の delta を受け取るまで（TTFT）
    total_s: float  # 送ってから done を受け取るまで
    deltas: int


async def measure(client: httpx2.AsyncClient, url: str, body: dict) -> Measurement:
    sent = time.perf_counter()
    start_s = ttft_s = total_s = None
    deltas = 0
    block: list[str] = []
    async with client.stream("POST", url, json=body) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if line:
                block.append(line)
                continue
            now = time.perf_counter() - sent  # 空行＝1ブロックが届いた時刻
            for ev in sse_events([*block, ""]):
                if ev["event"] == "start":
                    start_s = now
                elif ev["event"] == "delta":
                    deltas += 1
                    ttft_s = now if ttft_s is None else ttft_s
                elif ev["event"] == "done":
                    total_s = now
            block = []
    if start_s is None or total_s is None:
        raise RuntimeError("start か done が届きませんでした")
    return Measurement(start_s, ttft_s, total_s, deltas)


async def main() -> None:
    # api コンテナの中から、いま 8000 番で動いているアプリ（APP_MODULE=src.session05.app:app）を測る
    async with httpx2.AsyncClient(timeout=60) as c:
        m = await measure(c, "http://127.0.0.1:8000/api/chat/stream",
                          {"message": "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"})
    print(f"start={m.start_s:.3f}s ttft={m.ttft_s:.3f}s total={m.total_s:.3f}s deltas={m.deltas}")


if __name__ == "__main__":
    asyncio.run(main())
