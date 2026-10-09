"""練習問題6の解答：照合の結果を Redis に短時間だけ覚えて、毎回の DB 照会を減らす。

- Redis のキーは s09:auth:<SHA-256>（平文は置かない）
- 覚えておくのは成功した照合だけ。期限付きのキーは、期限より長く覚えない
- 期限の判定は、覚えた値を使うときも注入した Clock の now で行う（Redis の TTL は実時間で進むため）
- 失効は「DB を commit → Redis から消す」の順。逆にすると、消した直後に古い状態を覚え直される
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import keys
from .keys import CurrentUser
from .models import ApiKey

CACHE_PREFIX = "s09:auth:"


class CachedAuthenticator:
    def __init__(self, redis: Redis, *, ttl_seconds: int = 60) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds
        self.db_lookups = 0  # DB で照合した回数（検証用）

    @staticmethod
    def cache_key(key_hash: str) -> str:
        return CACHE_PREFIX + key_hash

    async def authenticate(self, session: AsyncSession, presented: str, *, now: datetime) -> CurrentUser | None:
        if not keys.KEY_PATTERN.fullmatch(presented):
            return None
        name = self.cache_key(keys.hash_key(presented))
        raw = await self.redis.get(name)
        if raw is not None:
            data = json.loads(raw)
            expires_at = data.pop("expires_at")
            if expires_at is not None and now >= datetime.fromisoformat(expires_at):
                return None
            return CurrentUser(**data)
        self.db_lookups += 1
        result = await keys.authenticate(session, presented, now=now)
        if result.user is None:
            return None  # 失敗は覚えない（総当たりで Redis を埋められないように）
        ttl = self.ttl_seconds
        if result.expires_at is not None:
            ttl = min(ttl, int((result.expires_at - now).total_seconds()))
        if ttl > 0:
            value = {**asdict(result.user),
                     "expires_at": result.expires_at.isoformat() if result.expires_at else None}
            await self.redis.set(name, json.dumps(value, ensure_ascii=False), ex=ttl)
        return result.user

    async def revoke_and_forget(self, session: AsyncSession, user_id: str, key_id: str, *, now: datetime) -> bool:
        """失効を commit してから、覚えていた照合結果を消す（この関数がトランザクションを閉じる）。"""
        key_hash = await session.scalar(
            select(ApiKey.key_hash).where(ApiKey.id == key_id, ApiKey.user_id == user_id))
        if key_hash is None:
            return False
        await keys.revoke_key(session, user_id, key_id, now=now)
        await session.commit()
        await self.redis.delete(self.cache_key(key_hash))
        return True
