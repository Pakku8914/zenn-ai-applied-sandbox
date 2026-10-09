"""verify.py と verify_practice.py が共有する検証用の小道具（名前が verify で始まらないので単独では実行されない）。"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
from fastapi import FastAPI

from kondate.clock import FixedClock
from kondate.settings import get_settings
from kondate.verifykit import sse_events

from .loop import ToolResult
from .providers import LLMProvider, ToolCall, open_provider
from .tools import ToolContext

BASE = get_settings()
ROOT = Path(__file__).resolve().parents[2]
PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"

for name in ("kondate.session08",):  # ID やトレースバック入りのログを画面に出さない
    log = logging.getLogger(name)
    log.addHandler(logging.NullHandler())
    log.propagate = False


def fixed_context() -> ToolContext:
    return ToolContext(clock=FixedClock())  # 2026-10-02T18:00+09:00 で止まった時計


def fixture_texts() -> list[str]:
    """mockllm の kondate_tool_search が各ステップで返すテキスト（delta の数の期待値を計算するため）。"""
    data = json.loads((ROOT / "mockllm/fixtures/kondate_tool_search.json").read_text(encoding="utf-8"))
    out = []
    for step in data["steps"]:
        blocks = step.get("content") or [{"type": "text", "text": step.get("text", "")}]
        out.append("".join(b["text"] for b in blocks if b["type"] == "text"))
    return out


def call(name: str, input_: dict, id_: str = "toolu_test_1") -> ToolCall:
    return ToolCall(id_, name, input_)


def brief(r: ToolResult) -> str:
    return f"{r.name}:{'error' if r.is_error else 'ok'}"


@asynccontextmanager
async def mock_provider(name: str = "anthropic") -> AsyncIterator[LLMProvider]:
    """接続先を必ず mockllm に向けたプロバイダ（.env で実 API に向けていても課金しない）。"""
    async with open_provider(name, model=BASE.llm_model,
                             base_url=BASE.mockllm_url if name == "anthropic" else f"{BASE.mockllm_url}/v1",
                             api_key="mock-key", max_retries=0, timeout=30.0) as provider:
        yield provider


@asynccontextmanager
async def asgi_client(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
        yield client


async def post_events(app: FastAPI, body: dict) -> tuple[int, list[dict]]:
    async with asgi_client(app) as c:
        r = await c.post("/api/chat/stream", json=body)
    if r.status_code != 200:
        return r.status_code, [r.json()]
    return 200, [e for e in sse_events(r.text.splitlines()) if e["event"]]  # コメント（: ping）は除く


def shape(events: list[dict]) -> str:
    """イベント名の列を「start → delta×3 → tool_call」の形に縮める。"""
    runs: list[list] = []
    for ev in events:
        if runs and runs[-1][0] == ev["event"]:
            runs[-1][1] += 1
        else:
            runs.append([ev["event"], 1])
    return " → ".join(k if n == 1 else f"{k}×{n}" for k, n in runs)


def data_of(events: list[dict], name: str) -> list:
    return [e["data"] for e in events if e["event"] == name]


def pairs_ok(messages: list[dict]) -> bool:
    """tool_use を含む assistant の直後に、同じ id の tool_result だけを持つ user があるか。"""
    for i, m in enumerate(messages):
        uses = [b["id"] for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_use"] \
            if m["role"] == "assistant" and isinstance(m["content"], list) else []
        if not uses:
            continue
        nxt = messages[i + 1] if i + 1 < len(messages) else None
        if nxt is None or nxt["role"] != "user":
            return False
        if [b.get("tool_use_id") for b in nxt["content"]] != uses:
            return False
    return True


async def reset_mock() -> None:
    async with httpx2.AsyncClient(timeout=5) as c:
        (await c.post(f"{BASE.mockllm_url}/_mock/reset")).raise_for_status()


async def mock_stats() -> dict:
    async with httpx2.AsyncClient(timeout=5) as c:
        r = await c.get(f"{BASE.mockllm_url}/_mock/stats")
        r.raise_for_status()
        return r.json()
