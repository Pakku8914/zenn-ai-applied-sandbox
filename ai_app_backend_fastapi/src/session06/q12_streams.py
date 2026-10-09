"""後半の練習問題6：再送用の保存を、Redis のリストから Redis Streams（XADD / XRANGE）に置き換える。

キー：s06:xevents:<message_id>。エントリ ID は "<seq>-0"（seq は 1 からの連番＝SSE の id と同じ）。
"""

from __future__ import annotations

import logging

from fastapi.sse import ServerSentEvent
from redis.asyncio import Redis
from redis.exceptions import RedisError

from .resume import TERMINAL, TTL_SECONDS

logger = logging.getLogger("kondate.session06.q12")
PREFIX = "s06:xevents:"


def stream_key(message_id: str) -> str:
    return f"{PREFIX}{message_id}"


class StreamsEventLog:
    """EventLog と同じ使い方（append が id 付きのイベントを返す）で、保存先だけを Redis Streams にしたもの。"""

    def __init__(self, redis: Redis, message_id: str, ttl: int = TTL_SECONDS) -> None:
        self._redis, self._key, self._ttl = redis, stream_key(message_id), ttl
        self.seq = 0
        self.broken = False

    async def append(self, ev: ServerSentEvent) -> ServerSentEvent:
        self.seq += 1
        out = ServerSentEvent(event=ev.event, raw_data=ev.raw_data, id=str(self.seq))
        if self.broken:
            return out
        try:
            pipe = self._redis.pipeline(transaction=False)
            # ID を自分で決める（"<seq>-0"）。Redis は増えていく ID しか受け付けないので、順序の保証にもなる
            pipe.xadd(self._key, {"event": ev.event, "data": ev.raw_data}, id=f"{self.seq}-0")
            pipe.expire(self._key, self._ttl)
            await pipe.execute()
        except RedisError:
            self.broken = True
            logger.warning("event_log_unavailable key=%s", self._key)
        return out


async def load_replay_streams(redis: Redis, message_id: str, after: int) -> list[dict] | None:
    """load_replay() と同じ約束：保存が無い・最後まで届いていないなら None。"""
    key = stream_key(message_id)
    last = await redis.xrevrange(key, count=1)  # 最後の1件だけを読む（全件を読まずに完了を判定できる）
    if not last or last[0][1]["event"] not in TERMINAL:
        return None
    items = await redis.xrange(key, min=f"({after}-0", max="+")  # "(" は「その ID を含まない」
    return [{"id": entry_id.split("-")[0], "event": f["event"], "data": f["data"]} for entry_id, f in items]
