"""verify.py と verify_practice.py が共有する検証用の小道具（名前が verify で始まらないので単独では実行されない）。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from fastapi import FastAPI

from kondate.cache import make_redis
from kondate.settings import get_settings
from kondate.verifykit import eq

from .jsonlog import JsonFormatter
from .llm import LLMConfig

BASE = get_settings()
QUESTION = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"
ANSWER_HEAD = "鶏むね肉とキャベツがあるなら"  # mockllm の kondate_chat シナリオの書き出し
REQ_ID = re.compile(r"req_[0-9A-HJKMNP-TV-Z]{26}")
UPSTREAM_ID = re.compile(r"req_mock_\d{6}")
VALID_ID = "req_01ARZ3NDEKTSV4RRFFQ69G5FAV"
TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+09:00")


def mock_config(**update: object) -> LLMConfig:
    """接続先とキーを明示的に mockllm に向けた設定（.env で実 API に向けていても課金しない）。"""
    values: dict[str, object] = {"anthropic_api_key": "mock-key", "anthropic_base_url": BASE.mockllm_url,
                                 "llm_model": BASE.llm_model}
    return LLMConfig(**(values | update))


class JsonCapture(logging.Handler):
    """本物の JsonFormatter で整形した行を集める（画面には出さない＝期待される出力に ID や時刻を混ぜない）。"""

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))

    @property
    def records(self) -> list[dict]:
        return [json.loads(line) for line in self.lines]

    def for_request(self, request_id: str) -> list[dict]:
        return [r for r in self.records if r.get("request_id") == request_id]

    def clear(self) -> None:
        self.lines.clear()


def capture_json_logs(name: str = "kondate.session14") -> JsonCapture:
    log = logging.getLogger(name)
    for handler in list(log.handlers):
        log.removeHandler(handler)
    cap = JsonCapture()
    log.addHandler(cap)
    log.setLevel(logging.INFO)
    log.propagate = False
    return cap


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    """lifespan を回したうえで、ASGITransport 経由の HTTP クライアントを渡す。"""
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=30) as client:
            yield client


def assert_error(r: httpx2.Response, status: int, type_: str) -> str:
    """共通エラー本文の形・request_id・上流の文が漏れていないことを確かめ、request_id を返す。"""
    eq(r.status_code, status, f"status（本文 {r.text}）")
    err = r.json()["error"]
    eq(sorted(err), ["message", "request_id", "type"], "error のキー")
    eq(err["type"], type_, "error.type")
    assert REQ_ID.fullmatch(err["request_id"]), err["request_id"]
    eq(r.headers["x-request-id"], err["request_id"], "x-request-id ヘッダと本文の request_id")
    assert "req_mock_" not in r.text, f"上流の request-id がクライアントに漏れている: {r.text}"
    return err["request_id"]


async def clear_redis(prefix: str = "s14:") -> None:
    redis = make_redis()
    try:
        async for key in redis.scan_iter(f"{prefix}*"):
            await redis.delete(key)
    finally:
        await redis.aclose()


def guard_mock_env() -> None:
    """worker と同じ環境変数の接続先が mockllm であること（実 API に向いていたら課金しないよう止める）。"""
    assert LLMConfig().forwards_mock_headers, (
        "ANTHROPIC_BASE_URL が mockllm 以外を向いています。worker が実 API を呼ぶので、この検証は実行しません")


async def wait_job(client: httpx2.AsyncClient, job_id: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        r = await client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200, (r.status_code, r.text)
        job = r.json()
        if job["status"] in ("succeeded", "failed"):
            return job
        if time.monotonic() > deadline:
            raise AssertionError(f"{timeout} 秒待っても終わりません（docker compose restart worker を実行しましたか）: {job}")
        await asyncio.sleep(0.05)
