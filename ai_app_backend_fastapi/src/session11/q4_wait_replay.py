"""練習問題4の解答：同じ冪等キーの要求が処理中なら、すぐ 409 にせず、締め切りまで待ってから再生する。"""

from __future__ import annotations

import asyncio

from kondate.clock import Clock

from .idempotency import Begun, IdempotencyStore
from .retry import Deadline, Sleep


async def begin_or_wait(store: IdempotencyStore, scope: str, key: str, fp: str, *, clock: Clock,
                        timeout: float = 10.0, interval: float = 0.5, sleep: Sleep = asyncio.sleep) -> Begun:
    """in_progress のあいだ interval 秒ごとに見直す。完了すれば replay、相手が諦めれば new（引き継ぐ）を返す。

    timeout までに決着しなければ in_progress のまま返す（呼び出し側が 409 にする）。
    """
    deadline = Deadline(clock, timeout)
    while True:
        begun = await store.begin(scope, key, fp)
        if begun.outcome != "in_progress":
            return begun  # new / replay / conflict
        if deadline.remaining() <= interval:
            return begun  # 次に見直す前に締め切りが来る
        await sleep(interval)
