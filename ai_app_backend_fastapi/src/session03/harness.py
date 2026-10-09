"""verify.py と verify_practice.py が共有する検証用の小道具。

名前が verify で始まらないので verify-all.sh には拾われない。
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from fastapi import FastAPI

from kondate.settings import get_settings
from kondate.verifykit import eq
from src.session03.config import LLMSettings

BASE = get_settings()
QUESTION = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"
REQ_ID = re.compile(r"^req_[0-9A-HJKMNP-TV-Z]{26}$")  # req_ + ULID（Crockford Base32 の26文字）


class Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def capture_logs() -> Capture:
    """kondate.session03 のログを画面に出さずに集める（期待される出力に ID を混ぜないため）。"""
    log = logging.getLogger("kondate.session03")
    for handler in list(log.handlers):
        log.removeHandler(handler)
    cap = Capture()
    log.addHandler(cap)
    log.setLevel(logging.INFO)
    log.propagate = False
    return cap


def mock_settings(**update: object) -> LLMSettings:
    """接続先とキーを明示的に mockllm に向けた設定（.env で実 API に向けていても課金しない）。"""
    values: dict[str, object] = {
        "anthropic_api_key": "mock-key",
        "anthropic_base_url": BASE.mockllm_url,
        "llm_model": BASE.llm_model,
    }
    return LLMSettings(**(values | update))


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    """lifespan を回したうえで、ASGITransport 経由の HTTP クライアントを渡す。"""
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=30) as client:
            yield client


async def reset_mock() -> None:
    async with httpx2.AsyncClient(timeout=5) as c:
        (await c.post(f"{BASE.mockllm_url}/_mock/reset")).raise_for_status()


async def mock_stats() -> dict:
    async with httpx2.AsyncClient(timeout=5) as c:
        r = await c.get(f"{BASE.mockllm_url}/_mock/stats")
        r.raise_for_status()
        return r.json()


def assert_error(r: httpx2.Response, status: int, type_: str) -> None:
    """共通エラー本文の形・request_id・上流の文が漏れていないことをまとめて確かめる。"""
    eq(r.status_code, status, f"status（本文 {r.text}）")
    err = r.json()["error"]
    eq(sorted(err), ["message", "request_id", "type"], "error のキー")
    eq(err["type"], type_, "error.type")
    assert REQ_ID.match(err["request_id"]), err["request_id"]
    eq(r.headers["x-request-id"], err["request_id"], "x-request-id ヘッダと本文の request_id")
    assert "mockllm" not in r.text and "req_mock_" not in r.text, f"上流の文が漏れている: {r.text}"
