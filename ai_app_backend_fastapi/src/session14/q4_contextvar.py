"""問題4の解答：グローバル変数の request_id は、同時に処理している別のリクエストに上書きされる。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from .middleware import choose_request_id

CURRENT: str | None = None  # Bad：プロセスに1つしかない
current_var: ContextVar[str | None] = ContextVar("q4_request_id", default=None)  # Good：タスクごとに分かれる

Handler = Callable[[str, float, list[tuple[str, str | None]]], Awaitable[None]]


async def handle_global(rid: str, delay: float, seen: list[tuple[str, str | None]]) -> None:
    global CURRENT
    CURRENT = rid
    await asyncio.sleep(delay)  # 上流を待つ間に、別のリクエストが CURRENT を書き換える
    seen.append((rid, CURRENT))


async def handle_contextvar(rid: str, delay: float, seen: list[tuple[str, str | None]]) -> None:
    current_var.set(rid)
    await asyncio.sleep(delay)
    seen.append((rid, current_var.get()))


async def run(handler: Handler) -> list[tuple[str, str | None]]:
    """req_A（遅い）と req_B（速い）を同時に処理し、(自分の ID, 最後に見えた ID) を返す。"""
    seen: list[tuple[str, str | None]] = []
    await asyncio.gather(handler("req_A", 0.05, seen), handler("req_B", 0.01, seen))  # gather は別々のタスクにする
    return sorted(seen)


async def in_threads(rid: str) -> tuple[str | None, str | None]:
    """スレッドへ渡すとき：asyncio.to_thread は文脈を写して渡し、run_in_executor は渡さない。"""
    current_var.set(rid)
    via_to_thread = await asyncio.to_thread(current_var.get)
    via_executor = await asyncio.get_running_loop().run_in_executor(None, current_var.get)
    return via_to_thread, via_executor


def id_sources(values: list[str | None]) -> list[tuple[str, bool]]:
    """本文の choose_request_id() に1つずつ渡し、(出どころ, 受け取った値をそのまま使ったか) を返す。"""
    result: list[tuple[str, bool]] = []
    for value in values:
        rid, source = choose_request_id(value)
        result.append((source, rid == value))
    return result
