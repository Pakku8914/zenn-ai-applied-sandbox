"""問題6：CancelledError を握りつぶすと何が起きるかを、決まった順番で確かめる。

    docker compose exec api python -m src.session11.solutions.q6_swallow
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import aclosing

Send = Callable[[str], Awaitable[None]]


class HeldStream:
    """1つ目の差分を出したあと、続きを出さずに待ち続けるストリーム（遅い LLM の代わり）。閉じられたかを記録する。"""

    def __init__(self) -> None:
        self.closed = False

    async def events(self):
        try:
            yield "鶏むね肉とキ"
            await asyncio.Event().wait()
            yield "ャベツ"
        finally:
            self.closed = True


async def bad_turn(stream: HeldStream, send: Send) -> None:
    try:
        async for delta in stream.events():
            await send(f"reply_delta:{delta}")
        await send("turn_end")
    except asyncio.CancelledError:
        await send("turn_end")           # 「片付け」のつもりで終わりを知らせ、取り消しを握りつぶしている


async def good_turn(stream: HeldStream, send: Send) -> None:
    async with aclosing(stream.events()) as events:   # 片付けは with と finally に任せ、CancelledError は上へ伝える
        async for delta in events:
            await send(f"reply_delta:{delta}")
    await send("turn_end")


async def run(turn: Callable[[HeldStream, Send], Awaitable[None]]) -> dict:
    sent: list[str] = []
    first = asyncio.Event()

    async def send(message: str) -> None:
        sent.append(message)
        if message.startswith("reply_delta"):
            first.set()

    stream = HeldStream()
    task = asyncio.create_task(turn(stream, send))
    await first.wait()                   # 1つ目の差分を送ったところで割り込む
    task.cancel()
    await asyncio.wait({task})
    sent.append("interrupted")
    return {"sent": sent, "cancelled": task.cancelled(), "closed": stream.closed}


async def main_async() -> None:
    for name, turn in (("握りつぶす", bad_turn), ("伝える", good_turn)):
        r = await run(turn)
        print(f"{name}: 送った順 {r['sent']}・task.cancelled() {r['cancelled']}・ストリームを閉じた {r['closed']}")


if __name__ == "__main__":
    asyncio.run(main_async())
