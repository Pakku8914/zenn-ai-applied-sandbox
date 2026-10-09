"""id と Last-Event-ID による再送。session06/resume.py のコピー（キーの接頭辞を review02: に変えた）。

キー：review02:events:<message_id>（リスト。1要素が1イベントの JSON {"id", "event", "data"}）。TTL 300 秒。
再送できるのは、最後まで（done か error まで）保存できたストリームだけ。
"""

from __future__ import annotations

import json
import logging
import re

from fastapi.sse import ServerSentEvent
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger("kondate.review02.resume")

PREFIX = "review02:events:"
TTL_SECONDS = 300  # 再接続を待つのは数分で十分。無期限に残すとメモリを食い、他人に読まれる窓も広がる
TERMINAL = frozenset({"done", "error"})
_LAST_ID = re.compile(r"[0-9]{1,9}")  # [0-9] は ASCII の数字だけ（全角の「３」は通さない）


def events_key(message_id: str) -> str:
    return f"{PREFIX}{message_id}"


class EventLog:
    """送るイベントに 1 から順に id を付け、Redis に書いてから返す。Redis が落ちても回答は止めない。"""

    def __init__(self, redis: Redis, message_id: str, ttl: int = TTL_SECONDS) -> None:
        self._redis, self._key, self._ttl = redis, events_key(message_id), ttl
        self.seq = 0
        self.broken = False

    async def append(self, ev: ServerSentEvent) -> ServerSentEvent:
        self.seq += 1
        out = ServerSentEvent(event=ev.event, raw_data=ev.raw_data, id=str(self.seq))
        if self.broken:
            return out
        entry = json.dumps({"id": str(self.seq), "event": ev.event, "data": ev.raw_data}, ensure_ascii=False)
        try:
            pipe = self._redis.pipeline(transaction=False)  # RPUSH と EXPIRE を1往復で送る
            pipe.rpush(self._key, entry)
            pipe.expire(self._key, self._ttl)
            await pipe.execute()
        except RedisError:
            self.broken = True  # 再送は付加機能。以降は保存をあきらめ、送信だけ続ける
            logger.warning("event_log_unavailable key=%s", self._key)
        return out


def parse_last_event_id(raw: str | None) -> int:
    """Last-Event-ID を数に直す。無い・空なら 0（最初から）。数字以外は ValueError。"""
    if raw is None or raw == "":
        return 0
    if not _LAST_ID.fullmatch(raw):
        raise ValueError(f"Last-Event-ID の形式が正しくありません: {raw!r}")
    return int(raw)


async def load_replay(redis: Redis, message_id: str, after: int) -> list[dict] | None:
    """id が after より大きい保存済みイベント。保存が無い・最後まで届いていないなら None。"""
    raw = await redis.lrange(events_key(message_id), 0, -1)
    if not raw:
        return None
    entries = [json.loads(x) for x in raw]
    if entries[-1]["event"] not in TERMINAL:
        return None  # 途中で終わった（切断で上流を止めた）ストリーム。続きは存在しない
    return [e for e in entries if int(e["id"]) > after]


def format_entries(entries: list[dict]) -> str:
    """保存した形から SSE の行に戻す。data は保存時の1行の JSON をそのまま使う。"""
    return "".join(f"id: {e['id']}\nevent: {e['event']}\ndata: {e['data']}\n\n" for e in entries)
