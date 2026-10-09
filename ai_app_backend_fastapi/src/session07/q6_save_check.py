"""練習問題6（小問）の解答：保存を確かめてから done を送ること、途中で失敗したときに何が残るかを確かめる。"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import nullcontext
from unittest.mock import patch

import httpx2

from kondate.verifykit import sse_events

from . import app as chat
from .providers import FakeItem, FakeProvider
from .tokens import ApproxTokenCounter


async def never_saved(*args: object, **kwargs: object) -> bool:
    """保存に失敗したことにする偽物（DB には何も書かず False を返す）。"""
    return False


async def run_turn(policy: str, script: Sequence[FakeItem], *,
                   save_ok: bool = True) -> tuple[list[str], str | None, int]:
    """1往復を送り、(イベント名の列, error の type, DB に残った発言の数) を返す。"""
    hs = chat.HistorySettings(history_on_failure=policy)
    chat.app.dependency_overrides.update({
        chat.get_provider: lambda: FakeProvider(script),
        chat.get_counter: lambda: ApproxTokenCounter(),  # count_tokens もネットワークに出さない
        chat.get_history_settings: lambda: hs,
    })
    try:
        transport = httpx2.ASGITransport(app=chat.app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as c:
            cid = (await c.post("/api/conversations", json={"user_id": "u006"})).json()["id"]
            # post_message は呼ぶたびにモジュールの save_turn を探すので、モジュールの属性を差し替えれば効く
            with patch.object(chat, "save_turn", never_saved) if not save_ok else nullcontext():
                r = await c.post(f"/api/conversations/{cid}/messages", json={"content": "二日目の献立は？"})
            saved = len((await c.get(f"/api/conversations/{cid}")).json()["messages"])
    finally:
        chat.app.dependency_overrides.clear()
    events = [ev for ev in sse_events(r.text.splitlines()) if ev["event"]]
    names = [ev["event"] for ev in events]
    error = events[-1]["data"]["type"] if names[-1] == "error" else None
    return names, error, saved
