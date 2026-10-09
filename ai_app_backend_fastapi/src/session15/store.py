"""1往復の保存先。DB（スキーマ s15）が正本、Redis（キー s15:）は今日の使用量の写し。

アプリは TurnStore（Protocol）だけを見る。単体テストでは MemoryStore に、結合テストでは SqlStore に差し替える。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from redis.asyncio import Redis
from sqlalchemy import DateTime, Integer, MetaData, String, Text, Uuid, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from kondate.clock import Clock

SCHEMA = "s15"
REDIS_PREFIX = "s15:"
USAGE_FIELDS = ("turns", "input_tokens", "output_tokens")
USAGE_TTL = 2 * 24 * 3600  # 今日の使用量の写しは2日で消える（正本は DB）


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class ChatTurn(Base):
    __tablename__ = "chat_turns"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)  # start イベントの message_id
    request_id: Mapped[str] = mapped_column(String(40), unique=True)
    prompt: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


async def create_tables(engine: AsyncEngine, *, drop_first: bool = False) -> None:
    """スキーマ s15 と表を作る（この章は Alembic を使わない。テストの準備を短くするため）。"""
    async with engine.begin() as conn:
        if drop_first:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)


@dataclass(frozen=True)
class Turn:
    message_id: str
    request_id: str
    prompt: str
    answer: str
    input_tokens: int
    output_tokens: int


class TurnStore(Protocol):
    async def save_turn(self, turn: Turn) -> None: ...

    async def usage_today(self) -> dict: ...


def usage_key(clock: Clock) -> str:
    return f"{REDIS_PREFIX}usage:{clock.now():%Y%m%d}"


class SqlStore:
    """本物の保存先。DB に1行書いてから、Redis の今日の使用量を足す。"""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], redis: Redis, clock: Clock) -> None:
        self._sessions = sessions
        self._redis = redis
        self._clock = clock

    async def save_turn(self, turn: Turn) -> None:
        async with self._sessions.begin() as session:  # 抜けるときに commit（例外なら rollback）
            session.add(ChatTurn(id=turn.message_id, request_id=turn.request_id, prompt=turn.prompt,
                                 answer=turn.answer, input_tokens=turn.input_tokens,
                                 output_tokens=turn.output_tokens, created_at=self._clock.now()))
        key = usage_key(self._clock)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hincrby(key, "turns", 1)
            pipe.hincrby(key, "input_tokens", turn.input_tokens)
            pipe.hincrby(key, "output_tokens", turn.output_tokens)
            pipe.expire(key, USAGE_TTL)
            await pipe.execute()

    async def usage_today(self) -> dict:
        raw = await self._redis.hgetall(usage_key(self._clock))
        return {"date": f"{self._clock.now():%Y-%m-%d}", **{k: int(raw.get(k, 0)) for k in USAGE_FIELDS}}


class MemoryStore:
    """単体テスト用の保存先。DB も Redis も使わず、リストに貯める。"""

    def __init__(self, clock: Clock) -> None:
        self.turns: list[Turn] = []
        self._clock = clock

    async def save_turn(self, turn: Turn) -> None:
        self.turns.append(turn)

    async def usage_today(self) -> dict:
        return {"date": f"{self._clock.now():%Y-%m-%d}", "turns": len(self.turns),
                "input_tokens": sum(t.input_tokens for t in self.turns),
                "output_tokens": sum(t.output_tokens for t in self.turns)}
