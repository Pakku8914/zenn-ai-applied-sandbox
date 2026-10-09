"""verify.py が使う検証用の小道具（名前が verify で始まらないので単独では実行されない）。

アプリは create_app() で作り直し、ログは画面に出さない（期待される出力に ID を混ぜないため）。
上流・時計・Redis・制限・予算・ジョブの設定は、依存性の差し替え（dependency_overrides）で入れ替える。
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

import anthropic
import httpx2
from sqlalchemy import text

from kondate.cache import make_redis
from kondate.clock import Clock, FixedClock
from kondate.db import SessionLocal, engine
from kondate.settings import get_settings
from kondate.verifykit import check, eq

from . import chat, deps, jobs, keys, ratelimit
from .app import build_routes, create_app, get_probe
from .budget import BudgetSettings
from .contract import check_ui_response
from .fallback import Route
from .lifecycle import Drain, StreamGate
from .limiter import LimitSettings
from .loop import ToolLimits
from .probes import ReadinessProbe, build_checks
from .providers import FakeProvider, LLMProvider, ToolCall, Usage, fake_script
from .retry import RetryPolicy
from .settings import FinalSettings

BASE = get_settings()
ROOT = Path(__file__).resolve().parents[2]
INI = "src/final/alembic.ini"
PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"
SETTINGS = FinalSettings(anthropic_base_url=BASE.mockllm_url)  # 上流は必ず mockllm（.env で実 API に向けていても課金しない）
APP = create_app(SETTINGS, configure_logging=False)
FIXTURE_CALLS = [("search_recipes", {"ingredients": ["鶏むね肉", "キャベツ"], "max_minutes": 20}),
                 ("get_recipe", {"recipe_id": "R001"})]

_log = logging.getLogger("kondate.final")
_log.handlers.clear()  # import した src.final.app が付けた JSON の出力先を外す
_log.addHandler(logging.NullHandler())
_log.propagate = False
_log.setLevel(logging.INFO)


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


# ---------------------------------------------------------------- DB と Redis


def alembic(*args: str) -> str:
    r = subprocess.run(["alembic", "-c", INI, *args], cwd=ROOT, capture_output=True, text=True)
    eq(r.returncode, 0, f"alembic {' '.join(args)}\n{r.stdout}{r.stderr}")
    return r.stdout + r.stderr


async def prepare_db() -> None:
    """final を消してマイグレーションを当て直し、5人を登録する（他のセッションのスキーマには触れない）。"""
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS final CASCADE"))
    await asyncio.to_thread(alembic, "upgrade", "head")
    async with SessionLocal() as s:
        await keys.seed_users(s)
        await s.commit()


async def clear_redis() -> None:
    redis = make_redis()
    try:
        async for key in redis.scan_iter("final:*"):
            await redis.delete(key)
    finally:
        await redis.aclose()


async def fresh() -> None:
    """会話・発言・台帳と、Redis の final: を空にする（ユーザーと API キーは残す）。"""
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE final.messages, final.conversations, final.usage_events"))
    await clear_redis()


async def rows(sql: str, **params: object) -> list[tuple]:
    async with engine.connect() as conn:
        return [tuple(r) for r in await conn.execute(text(sql), params)]


async def scalar(sql: str, **params: object) -> object:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar()


async def issue(user_id: str, clock: Clock) -> str:
    async with SessionLocal() as s:
        issued = await keys.issue_key(s, user_id, now=clock.now())
        await s.commit()
    return issued.key


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


# ---------------------------------------------------------------- 上流


def fixture_texts() -> list[str]:
    data = json.loads((ROOT / "mockllm/fixtures/kondate_tool_search.json").read_text(encoding="utf-8"))
    out = []
    for step in data["steps"]:
        blocks = step.get("content") or [{"type": "text", "text": step.get("text", "")}]
        out.append("".join(b["text"] for b in blocks if b["type"] == "text"))
    return out


def fake_tool_search() -> FakeProvider:
    """mockllm の kondate_tool_search と同じ3ステップを返す Fake。usage はステップごとに 100/10・200/20・300/30。"""
    t = fixture_texts()
    return FakeProvider(
        fake_script(t[0], tool_calls=[ToolCall("toolu_f1", *FIXTURE_CALLS[0])], usage=Usage(100, 10)),
        fake_script(t[1], tool_calls=[ToolCall("toolu_f2", *FIXTURE_CALLS[1])], usage=Usage(200, 20)),
        fake_script(t[2], usage=Usage(300, 30)))


def fake_text(text_: str = "鶏むね肉とキャベツの塩炒めがおすすめです。", usage: Usage = Usage(34, 20)) -> FakeProvider:
    return FakeProvider(fake_script(text_, usage=usage))


def fake_routes(provider: LLMProvider) -> list[Route]:
    policy = RetryPolicy(max_attempts=2)
    return [Route("primary", provider, None, policy), Route("light", provider, BASE.llm_model_light, policy)]


@asynccontextmanager
async def mock_routes() -> AsyncIterator[list[Route]]:
    client = anthropic.AsyncAnthropic(base_url=BASE.mockllm_url, api_key="mock-key", max_retries=0, timeout=30.0)
    try:
        yield build_routes(client, SETTINGS)
    finally:
        await client.close()


async def reset_mock() -> None:
    async with httpx2.AsyncClient(timeout=5) as c:
        (await c.post(f"{BASE.mockllm_url}/_mock/reset")).raise_for_status()


async def mock_stats() -> dict:
    async with httpx2.AsyncClient(timeout=5) as c:
        r = await c.get(f"{BASE.mockllm_url}/_mock/stats")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------- アプリの呼び出し


async def no_sleep(_: float) -> None:
    """リトライの待ちを実際には待たない（FixedClock なので締め切りも進まない）。"""


def _const(value: object) -> Callable[[], object]:
    return lambda: value  # lambda v=value: v と書くと FastAPI がクエリパラメータと見なして落ちる


@asynccontextmanager
async def client_for(routes: Sequence[Route], *, clock: Clock | None = None, limits: LimitSettings | None = None,
                     budget: BudgetSettings | None = None, tool_limits: ToolLimits | None = None,
                     job_settings: jobs.JobSettings | None = None) -> AsyncIterator[httpx2.AsyncClient]:
    """同一プロセスで APP を呼ぶクライアント。drain と関所は、この check のイベントループで作り直す。"""
    redis = make_redis()
    http = httpx2.AsyncClient(timeout=2)
    probe = ReadinessProbe(build_checks(engine, redis, http, mock_url=BASE.mockllm_url), 1.0)
    APP.state.drain = Drain(SETTINGS.drain_grace_seconds)
    APP.state.gate = StreamGate(SETTINGS.max_streams_per_worker)
    APP.state.outcomes.clear()
    o = APP.dependency_overrides
    o.clear()
    o[chat.get_routes] = _const(list(routes))
    o[ratelimit.get_redis] = _const(redis)
    o[deps.get_clock] = _const(clock or FixedClock())
    o[chat.get_sleep] = _const(no_sleep)
    o[get_probe] = _const(probe)
    o[ratelimit.get_limit_settings] = _const(limits or LimitSettings())
    o[chat.get_budget_settings] = _const(budget or BudgetSettings())
    o[chat.get_tool_limits] = _const(tool_limits or ToolLimits())
    o[jobs.get_job_settings] = _const(job_settings or jobs.JobSettings(work_seconds=0.05))
    transport = httpx2.ASGITransport(app=APP, raise_app_exceptions=False)
    try:
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
            yield client
    finally:
        o.clear()
        await http.aclose()
        await redis.aclose()


def user_message(text_: str, mid: str) -> dict:
    return {"id": mid, "role": "user", "parts": [{"type": "text", "text": text_}]}


async def post_chat(c: httpx2.AsyncClient, key: str, chat_id: str, messages: list[dict], *,
                    trigger: str = "submit-message", message_id: str | None = None,
                    headers: dict[str, str] | None = None) -> httpx2.Response:
    body: dict = {"id": chat_id, "messages": messages, "trigger": trigger}
    if message_id is not None:
        body["messageId"] = message_id
    return await c.post("/api/chat", json=body, headers={**bearer(key), **(headers or {})})


def ui(r: httpx2.Response) -> list[dict]:
    """契約の検査を通してからチャンクの列を返す。"""
    return check_ui_response(r.status_code, dict(r.headers), r.text)


async def conversation(c: httpx2.AsyncClient, key: str, chat_id: str) -> list[dict]:
    r = await c.get(f"/api/conversations/{chat_id}", headers=bearer(key))
    eq(r.status_code, 200, "GET /api/conversations/{id}")
    return r.json()


def assert_error(r: httpx2.Response, status: int, type_: str, message: str | None = None) -> dict:
    """開始前のエラー：JSON の本文 {error: {type, message, request_id}}・request_id はヘッダと同じ。"""
    eq(r.status_code, status, f"status（{r.text[:120]}）")
    eq(r.headers["content-type"].split(";")[0], "application/json", "content-type")
    err = r.json()["error"]
    eq(sorted(err), ["message", "request_id", "type"], "本文のキー")
    eq(err["type"], type_, "type")
    eq(err["request_id"], r.headers["x-request-id"], "request_id とヘッダ")
    if message is not None:
        eq(err["message"], message, "message")
    return err


async def wait_job(c: httpx2.AsyncClient, job_id: str, key: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        r = await c.get(f"/api/jobs/{job_id}", headers=bearer(key))
        assert r.status_code == 200, (r.status_code, r.text)
        job = r.json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        if time.monotonic() > deadline:
            raise AssertionError(f"{timeout} 秒待ってもジョブが終わりません（worker は動いていますか）: {job}")
        await asyncio.sleep(0.05)
