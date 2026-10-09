"""練習問題1：失敗の位置で、応答の形（JSON か error イベントか）がどう変わるかを観察する。

    docker compose exec api python -m src.session06.q1_boundary
"""

from __future__ import annotations

import asyncio

from kondate.verifykit import sse_events

from .app import app
from .harness import PROMPT, asgi_client, quiet_logs, shape, wired
from .providers import FakeItem, FakeProvider, ProviderError, TextDelta

CASES: dict[str, list[FakeItem]] = {
    "位置0": [ProviderError("overloaded", provider="fake", status_code=529)],
    "位置1": [TextDelta("鶏むね肉とキ"), ProviderError("connection", provider="fake")],
    "位置2": [TextDelta("鶏むね肉とキ"), TextDelta("ャベツの塩炒"),
            ProviderError("stream_error", provider="fake", status_code=200)],
}


async def observe(script: list[FakeItem]) -> tuple[int, str]:
    """(ステータス, JSON なら error.type／SSE なら「イベント列（error の種別）」) を返す。"""
    async with wired(app, FakeProvider(script)), asgi_client(app) as c:
        r = await c.post("/api/chat/stream", json={"message": PROMPT})
    if r.headers["content-type"].startswith("application/json"):
        return r.status_code, f"{r.json()['error']['type']}（JSON）"
    events = sse_events(r.text.split("\n"))
    return r.status_code, f"{shape([e['event'] for e in events])}（{events[-1]['data']['type']}）"


async def main() -> None:
    quiet_logs()  # 失敗のログ（request_id 入り）を画面に出さない
    for name, script in CASES.items():
        status, what = await observe(script)
        print(f"{name}: {status} {what}")


if __name__ == "__main__":
    asyncio.run(main())
