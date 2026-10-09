"""verify.py・verify_practice.py・練習問題の解答が共有する検証用の小道具。

名前が verify で始まらないので verify-all.sh には拾われない。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import httpx2
from fastapi import FastAPI

from kondate.settings import get_settings
from kondate.verifykit import eq, sse_events

from .config import ProdSettings

BASE = get_settings()
PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"
REQ_ID = re.compile(r"^req_[0-9A-HJKMNP-TV-Z]{26}$")


def lab_values() -> dict[str, object]:
    """接続先とキーを明示的に mockllm に向けた値（.env で実 API に向けていても課金しない）。"""
    return {"database_url": BASE.database_url, "redis_url": BASE.redis_url, "anthropic_api_key": "mock-key",
            "anthropic_base_url": BASE.mockllm_url, "llm_model": BASE.llm_model}


def lab_settings(**update: object) -> ProdSettings:
    return ProdSettings(**(lab_values() | update))  # type: ignore[arg-type]


class Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def events(self, name: str) -> list[logging.LogRecord]:
        return [r for r in self.records if r.getMessage() == name]


def quiet() -> Capture:
    """kondate.session16 のログを画面に出さずに集める（期待される出力に時刻や ID を混ぜないため）。"""
    log = logging.getLogger("kondate.session16")
    for handler in list(log.handlers):
        log.removeHandler(handler)
    cap = Capture()
    log.addHandler(cap)
    log.setLevel(logging.INFO)
    log.propagate = False
    return cap


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    """lifespan を回したうえで、ASGITransport 経由の HTTP クライアントを渡す。"""
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
            yield client


@dataclass
class Run:
    status: int
    headers: dict[str, str]
    events: list[dict] = field(default_factory=list)
    body: dict | None = None  # SSE が始まらなかったときの JSON

    @property
    def names(self) -> list[str | None]:
        return [e["event"] for e in self.events]


async def stream_chat(client: httpx2.AsyncClient, *, tps: int, ttft: int = 0) -> Run:
    """POST /api/chat/stream を1行ずつ読む。tps・ttft は mockllm の遅延ヘッダ（アプリが上流へ渡す）。"""
    headers = {"x-mock-tps": str(tps), "x-mock-ttft-ms": str(ttft)}
    async with client.stream("POST", "/api/chat/stream", json={"message": PROMPT}, headers=headers) as r:
        if r.headers.get("content-type", "").split(";")[0] != "text/event-stream":
            await r.aread()
            return Run(r.status_code, dict(r.headers), body=r.json())
        lines = [line async for line in r.aiter_lines()]
    return Run(r.status_code, dict(r.headers), sse_events([*lines, ""]))


def shape(names: list[str | None]) -> str:
    """["start", "delta", "delta", "done"] を「start → delta×2 → done」に縮める。"""
    runs: list[list] = []
    for n in names:
        label = n or ": ping"
        if runs and runs[-1][0] == label:
            runs[-1][1] += 1
        else:
            runs.append([label, 1])
    return " → ".join(k if c == 1 else f"{k}×{c}" for k, c in runs)


async def wait_until(predicate: Callable[[], bool], timeout: float, what: str) -> float:
    started = time.perf_counter()
    while not predicate():
        if time.perf_counter() - started > timeout:
            raise AssertionError(f"{timeout} 秒待っても {what}")
        await asyncio.sleep(0.02)
    return time.perf_counter() - started


def assert_error(r: httpx2.Response, status: int, type_: str) -> None:
    """共通エラー本文の形・request_id・上流の文が漏れていないことをまとめて確かめる。"""
    eq(r.status_code, status, f"status（本文 {r.text}）")
    err = r.json()["error"]
    eq(sorted(err), ["message", "request_id", "type"], "error のキー")
    eq(err["type"], type_, "error.type")
    assert REQ_ID.match(err["request_id"]), err["request_id"]
    eq(r.headers["x-request-id"], err["request_id"], "x-request-id ヘッダと本文の request_id")
    assert "mockllm" not in r.text and "req_mock_" not in r.text, f"上流の文が漏れている: {r.text}"
