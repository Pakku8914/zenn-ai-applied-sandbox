"""API キー認証とユーザー単位の分離（会話の CRUD とキーの管理。LLM は呼ばない）。

事前に（api コンテナの /app で）：
  docker compose exec api alembic -c src/session09/alembic.ini upgrade head
  docker compose exec api python -m src.session09.cli seed-users
  docker compose exec api python -m src.session09.cli issue u001 --name ノートPC
起動：APP_MODULE=src.session09.app:app docker compose up -d --wait api
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from kondate.clock import JST
from kondate.db import engine

from . import keys, repo
from .auth import ClockDep, CurrentUserDep
from .deps import SessionDep
from .errors import ApiError, install_error_handling
from .keys import KeyStatus


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    api_key_rotation_grace_seconds: int = 86400  # ローテーション後、古いキーも使える猶予（既定 24 時間）


def get_auth_settings() -> AuthSettings:
    return AuthSettings()


AuthSettingsDep = Annotated[AuthSettings, Depends(get_auth_settings)]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


app = FastAPI(title="こんだてAI（API キー認証とユーザー単位の分離）", lifespan=lifespan)
install_error_handling(app)

NO_STORE = "no-store"  # 平文のキーを含む応答を、ブラウザやプロキシに保存させない


def jst(dt: datetime | None) -> datetime | None:
    return None if dt is None else dt.astimezone(JST)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 本文に user_id などの余計な項目が来たら 422


class ConversationIn(Strict):
    title: str | None = Field(default=None, max_length=200)


class ConversationPatch(Strict):
    title: str = Field(min_length=1, max_length=200)


class ConversationOut(BaseModel):
    id: str
    title: str | None


class MessageOut(BaseModel):
    id: str
    seq: int
    role: str
    content: list[dict]
    status: str


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class MeOut(BaseModel):
    id: str
    name: str
    plan: str


class KeyIn(Strict):
    name: str | None = Field(default=None, max_length=50)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class KeyOut(BaseModel):
    """一覧に出すのは見分けるための情報だけ（key_hash も平文も持たない）。"""

    id: str
    prefix: str
    name: str | None
    status: KeyStatus
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None


class IssuedKeyOut(BaseModel):
    api_key: str  # この応答でしか見られない
    id: str
    prefix: str
    name: str | None
    expires_at: datetime | None


def issued_out(issued: keys.IssuedKey, response: Response) -> IssuedKeyOut:
    response.headers["Cache-Control"] = NO_STORE
    return IssuedKeyOut(api_key=issued.key, id=issued.id, prefix=issued.prefix, name=issued.name,
                        expires_at=jst(issued.expires_at))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/me")
async def me(user: CurrentUserDep) -> MeOut:
    return MeOut(id=user.id, name=user.name, plan=user.plan)


@app.get("/api/conversations")
async def list_conversations(user: CurrentUserDep, session: SessionDep) -> list[ConversationOut]:
    rows = await repo.list_conversations(session, user.id)
    return [ConversationOut(id=c.id, title=c.title) for c in rows]


@app.post("/api/conversations", status_code=201)
async def create_conversation(body: ConversationIn, user: CurrentUserDep, session: SessionDep) -> ConversationOut:
    conv = await repo.create_conversation(session, user_id=user.id, title=body.title)  # 持ち主は認証から決める
    await session.commit()
    return ConversationOut(id=conv.id, title=conv.title)


@app.get("/api/conversations/{conversation_id}")
async def show_conversation(conversation_id: UUID, user: CurrentUserDep, session: SessionDep) -> ConversationDetail:
    conv = await repo.get_conversation(session, user.id, str(conversation_id))
    if conv is None:
        raise ApiError(404, "not_found")  # 存在しない会話と他人の会話を区別しない
    rows = await repo.load_messages(session, user.id, conv.id)
    return ConversationDetail(id=conv.id, title=conv.title, messages=[
        MessageOut(id=r.id, seq=r.seq, role=r.role, content=r.content, status=r.status) for r in rows])


@app.patch("/api/conversations/{conversation_id}")
async def rename_conversation(conversation_id: UUID, body: ConversationPatch, user: CurrentUserDep,
                              session: SessionDep) -> ConversationOut:
    conv = await repo.rename_conversation(session, user.id, str(conversation_id), body.title)
    if conv is None:
        raise ApiError(404, "not_found")
    await session.commit()
    return ConversationOut(id=conv.id, title=conv.title)


@app.delete("/api/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: UUID, user: CurrentUserDep, session: SessionDep) -> None:
    if not await repo.delete_conversation(session, user.id, str(conversation_id)):
        raise ApiError(404, "not_found")
    await session.commit()


@app.get("/api/keys")
async def list_keys(user: CurrentUserDep, session: SessionDep, clock: ClockDep) -> list[KeyOut]:
    now = clock.now()
    return [KeyOut(id=k.id, prefix=k.prefix, name=k.name, status=keys.key_status(k, now),
                   created_at=jst(k.created_at), expires_at=jst(k.expires_at), revoked_at=jst(k.revoked_at))
            for k in await keys.list_keys(session, user.id)]


@app.post("/api/keys", status_code=201)
async def issue_key(body: KeyIn, response: Response, user: CurrentUserDep, session: SessionDep,
                    clock: ClockDep) -> IssuedKeyOut:
    ttl = timedelta(days=body.expires_in_days) if body.expires_in_days else None
    issued = await keys.issue_key(session, user.id, now=clock.now(), name=body.name, ttl=ttl)
    await session.commit()
    return issued_out(issued, response)


@app.post("/api/keys/{key_id}/rotate", status_code=201)
async def rotate_key(key_id: UUID, response: Response, user: CurrentUserDep, session: SessionDep,
                     clock: ClockDep, settings: AuthSettingsDep) -> IssuedKeyOut:
    issued = await keys.rotate_key(session, user.id, str(key_id), now=clock.now(),
                                   grace=timedelta(seconds=settings.api_key_rotation_grace_seconds))
    if issued is None:
        raise ApiError(404, "not_found")  # 他人のキー・存在しないキー・もう使えないキー
    await session.commit()
    return issued_out(issued, response)


@app.delete("/api/keys/{key_id}", status_code=204)
async def revoke_key(key_id: UUID, user: CurrentUserDep, session: SessionDep, clock: ClockDep) -> None:
    if not await keys.revoke_key(session, user.id, str(key_id), now=clock.now()):
        raise ApiError(404, "not_found")
    await session.commit()
