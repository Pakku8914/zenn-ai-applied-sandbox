"""verify.py と verify_practice.py が共有する検証用の小道具（名前が verify で始まらないので単独では実行されない）。"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import httpx2
from fastapi import FastAPI
from sqlalchemy import text

from kondate.clock import Clock
from kondate.db import SessionLocal, engine
from kondate.verifykit import check, eq

from . import keys
from .auth import get_clock
from .users import seed_users

ROOT = Path(__file__).resolve().parents[2]
INI = "src/session09/alembic.ini"
REQ_ID = re.compile(r"^req_[0-9A-HJKMNP-TV-Z]{26}$")


class Capture(logging.Handler):
    """ログを画面に出さずに集める（期待される出力に ID やキーの先頭を混ぜないため）。"""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


_root = logging.getLogger("kondate.session09")
_root.propagate = False
_root.setLevel(logging.INFO)
_root.addHandler(logging.NullHandler())


def capture_logs() -> Capture:
    for handler in list(_root.handlers):
        _root.removeHandler(handler)
    cap = Capture()
    _root.addHandler(cap)
    return cap


def dbcheck(name: str) -> Callable[[Callable[[], Awaitable[object]]], None]:
    """async の check。終わるたびに接続プールを捨てる（check ごとに別のイベントループで動くため）。"""
    def deco(fn: Callable[[], Awaitable[object]]) -> None:
        async def wrapped() -> object:
            try:
                return await fn()
            finally:
                await engine.dispose()
        check(name)(wrapped)
    return deco


def alembic(*args: str) -> str:
    r = subprocess.run(["alembic", "-c", INI, *args], cwd=ROOT, capture_output=True, text=True)
    eq(r.returncode, 0, f"alembic {' '.join(args)}\n{r.stdout}{r.stderr}")
    return r.stdout + r.stderr


def upgraded(log_text: str) -> list[str]:
    return re.findall(r"Running (?:upgrade|downgrade) \S* ?-> (\S+?),", log_text)


async def reset_schema() -> None:
    """s09 を消して作り直す（他のセッションのスキーマには触れない）。"""
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS s09 CASCADE"))


async def prepare_db() -> None:
    """s09 を作り直し、マイグレーションを当て、5人のユーザーを入れる。"""
    await reset_schema()
    await asyncio.to_thread(alembic, "upgrade", "head")
    async with SessionLocal() as s:
        await seed_users(s)
        await s.commit()


async def scalar(sql: str, **params: object) -> object:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar()


async def issue(user_id: str, clock: Clock, *, name: str | None = None,
                ttl: timedelta | None = None) -> keys.IssuedKey:
    async with SessionLocal() as s:
        issued = await keys.issue_key(s, user_id, now=clock.now(), name=name, ttl=ttl)
        await s.commit()
    return issued


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


@asynccontextmanager
async def client_for(app: FastAPI, clock: Clock | None = None) -> AsyncIterator[httpx2.AsyncClient]:
    """同一プロセスで app を呼ぶクライアント。clock を渡すと、認証と失効の判定をその時計で行う。"""
    if clock is not None:
        app.dependency_overrides[get_clock] = lambda: clock
    transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=30) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def assert_unauthorized(r: httpx2.Response) -> None:
    eq(r.status_code, 401, f"status（本文 {r.text}）")
    err = r.json()["error"]
    eq((err["type"], err["message"]), ("unauthorized", "認証が必要です"), "error の type と message")
    eq(r.headers.get("www-authenticate"), "Bearer", "WWW-Authenticate ヘッダ")
    assert REQ_ID.match(err["request_id"]), err["request_id"]
    eq(r.headers["x-request-id"], err["request_id"], "x-request-id と本文の request_id")


def reasons(cap: Capture) -> list[str]:
    return [m.group(1) for line in cap.lines if (m := re.search(r"auth_failed reason=(\w+)", line))]
