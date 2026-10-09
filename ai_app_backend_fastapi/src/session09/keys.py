"""API キーの発行・照合・失効・ローテーション。

平文のキーは保存しない。DB に置くのは SHA-256（照合用）と先頭8文字（人が見分ける用）だけ。
時刻はすべて引数の now（注入した Clock の値）で判定し、datetime.now() や SQL の now() を使わない。
ここでは commit しない：トランザクションの境界は呼び出し側が決める。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ApiKey, User

KEY_SCHEME = "kd_"
PREFIX_LEN = 8
KEY_PATTERN = re.compile(r"kd_[A-Za-z0-9_-]{43}")  # token_urlsafe(32) は43文字になる

KeyStatus = Literal["active", "expired", "revoked"]


def generate_key() -> str:
    """kd_ + 32バイト（256ビット）の暗号論的乱数を URL 安全な Base64 にしたもの。"""
    return KEY_SCHEME + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IssuedKey:
    """発行の結果。平文の key はこの値を返す応答で1回だけ見せる。repr（ログ・例外表示）には出さない。"""

    id: str
    prefix: str
    name: str | None
    expires_at: datetime | None
    key: str = field(repr=False)


@dataclass(frozen=True)
class CurrentUser:
    """認証で確かめた「いまの利用者」。ルートはこの id だけを信じる。"""

    id: str
    name: str
    plan: str
    key_id: str


@dataclass(frozen=True)
class AuthResult:
    user: CurrentUser | None
    reason: str  # ok / malformed / unknown / revoked / expired（ログ用。クライアントには返さない）
    prefix: str | None = None
    expires_at: datetime | None = None


def key_status(key: ApiKey, now: datetime) -> KeyStatus:
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
        return AuthResult(None, "malformed")  # 形の違う値は、先頭すら記録しない
    digest = hash_key(presented)
    prefix = presented[:PREFIX_LEN]
    rows = await session.execute(
        select(ApiKey, User).join(User, User.id == ApiKey.user_id).where(ApiKey.prefix == prefix))
    for key, user in rows:  # 先頭8文字が偶然同じキーが複数あっても、ハッシュで1つに決まる
        if not hmac.compare_digest(key.key_hash, digest):
            continue
        status = key_status(key, now)
        if status != "active":
            return AuthResult(None, status, prefix)
        return AuthResult(CurrentUser(user.id, user.name, user.plan, key.id), "ok", prefix, key.expires_at)
    return AuthResult(None, "unknown", prefix)


async def list_keys(session: AsyncSession, user_id: str) -> list[ApiKey]:
    rows = await session.scalars(
        select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at, ApiKey.id))
    return list(rows)


async def _own_key(session: AsyncSession, user_id: str, key_id: str, *, lock: bool = False) -> ApiKey | None:
    stmt = select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user_id)
    return await session.scalar(stmt.with_for_update() if lock else stmt)


async def revoke_key(session: AsyncSession, user_id: str, key_id: str, *, now: datetime) -> bool:
    """自分のキーを今すぐ使えなくする。自分のキーでなければ False（何度呼んでも最初の失効時刻のまま）。"""
    key = await _own_key(session, user_id, key_id, lock=True)
    if key is None:
        return False
    if key.revoked_at is None:
        key.revoked_at = now
        await session.flush()
    return True


async def rotate_key(session: AsyncSession, user_id: str, key_id: str, *, now: datetime,
                     grace: timedelta) -> IssuedKey | None:
    """新しいキーを発行し、古いキーは grace の後に期限切れにする。使えるキーでなければ None。"""
    old = await _own_key(session, user_id, key_id, lock=True)
    if old is None or key_status(old, now) != "active":
        return None
    lifetime = old.expires_at - old.created_at if old.expires_at else None  # 新しいキーも同じ長さの寿命にする
    deadline = now + grace
    if old.expires_at is None or old.expires_at > deadline:
        old.expires_at = deadline
    return await issue_key(session, user_id, now=now, name=old.name, ttl=lifetime)
