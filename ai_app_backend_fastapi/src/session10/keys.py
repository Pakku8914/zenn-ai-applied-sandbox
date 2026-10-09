"""API キーの発行と照合（session09/keys.py から発行・照合の部分をコピー。失効とローテーションは Session 9 を参照）。

平文のキーは保存しない。DB に置くのは SHA-256（照合用）と先頭8文字（人が見分ける用）だけ。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ApiKey, User

KEY_SCHEME = "kd_"
PREFIX_LEN = 8
KEY_PATTERN = re.compile(r"kd_[A-Za-z0-9_-]{43}")  # token_urlsafe(32) は43文字になる


def generate_key() -> str:
    return KEY_SCHEME + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IssuedKey:
    id: str
    prefix: str
    name: str | None
    expires_at: datetime | None
    key: str = field(repr=False)  # 平文。repr（ログ・例外表示）には出さない


@dataclass(frozen=True)
class CurrentUser:
    """認証で確かめた「いまの利用者」。plan でレート制限とクォータの上限が決まる。"""

    id: str
    name: str
    plan: str
    key_id: str


@dataclass(frozen=True)
class AuthResult:
    user: CurrentUser | None
    reason: str  # ok / malformed / unknown / revoked / expired（ログ用。クライアントには返さない）
    prefix: str | None = None


def key_status(key: ApiKey, now: datetime) -> str:
    if key.revoked_at is not None:
        return "revoked"
    if key.expires_at is not None and now >= key.expires_at:
        return "expired"
    return "active"


async def issue_key(session: AsyncSession, user_id: str, *, now: datetime, name: str | None = None,
                    ttl: timedelta | None = None) -> IssuedKey:
    key = generate_key()
    row = ApiKey(user_id=user_id, name=name, prefix=key[:PREFIX_LEN], key_hash=hash_key(key),
                 created_at=now, expires_at=now + ttl if ttl else None)
    session.add(row)
    await session.flush()
    return IssuedKey(id=row.id, prefix=row.prefix, name=row.name, expires_at=row.expires_at, key=key)


async def authenticate(session: AsyncSession, presented: str, *, now: datetime) -> AuthResult:
    """提示されたキーを照合する。どの理由で失敗しても、呼び出し側は同じ 401 を返すこと。"""
    if not KEY_PATTERN.fullmatch(presented):
        return AuthResult(None, "malformed")
    digest = hash_key(presented)
    prefix = presented[:PREFIX_LEN]
    rows = await session.execute(
        select(ApiKey, User).join(User, User.id == ApiKey.user_id).where(ApiKey.prefix == prefix))
    for key, user in rows:
        if not hmac.compare_digest(key.key_hash, digest):
            continue
        status = key_status(key, now)
        if status != "active":
            return AuthResult(None, status, prefix)
        return AuthResult(CurrentUser(user.id, user.name, user.plan, key.id), "ok", prefix)
    return AuthResult(None, "unknown", prefix)
