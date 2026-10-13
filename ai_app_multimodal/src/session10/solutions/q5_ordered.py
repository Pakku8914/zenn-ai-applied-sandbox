"""問題5：合成を最大 N 本まで同時に進めても、送るのは必ず文の順番（index の順）にする。

    docker compose exec api python -m src.session10.solutions.q5_ordered
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


async def speak_in_order(
    sentences: asyncio.Queue,                                  # 文が順に入り、最後に None が入る
    synthesize: Callable[[str], Awaitable[bytes]],
    send: Callable[[int, str, bytes], Awaitable[None]],
    concurrency: int = 2,
) -> None:
    gate = asyncio.Semaphore(concurrency)
    order: asyncio.Queue = asyncio.Queue()                     # (文, 合成のタスク) を、文の順に並べておく

    async def synth(text: str) -> bytes:
        async with gate:                                       # 同時に動く合成は concurrency 本まで
            return await synthesize(text)

    async def send_in_order() -> None:
        index = 0
        while (item := await order.get()) is not None:
            text, task = item
            await send(index, text, await task)                # index 番目が終わるまで待つ。後ろの文が先に終わっても抜かさない
            index += 1

    async with asyncio.TaskGroup() as tg:                      # どれかが失敗したら、残りの合成もまとめて取り消す
        tg.create_task(send_in_order())
        while (text := await sentences.get()) is not None:
            order.put_nowait((text, tg.create_task(synth(text))))
        order.put_nowait(None)


async def demo(concurrency: int) -> dict:
    """文ごとに合成の時間を変えた偽の合成で試す（B は A より先に終わる）。"""
    delays = {"A": 0.30, "B": 0.05, "C": 0.20, "D": 0.01, "E": 0.10}
    active = peak = 0
    finished: list[str] = []
    sent: list[tuple[int, str]] = []

    async def synthesize(text: str) -> bytes:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(delays[text])
        active -= 1
        finished.append(text)
        return text.encode()

    async def send(index: int, text: str, wav: bytes) -> None:
        sent.append((index, text))

    queue: asyncio.Queue = asyncio.Queue()
    for text in [*delays, None]:
        queue.put_nowait(text)
    await speak_in_order(queue, synthesize, send, concurrency)
    return {"sent": sent, "finished": finished, "peak": peak}


def main() -> int:
    for n in (1, 2):
        r = asyncio.run(demo(n))
        print(f"同時 {n} 本: 送った順 {[t for _, t in r['sent']]}・合成が終わった順 {r['finished']}・最大 {r['peak']} 本")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
