"""前半の練習問題5：ストリームの結末（StreamOutcome）を、usage の出どころごとに集計する。

    docker compose exec api python -m src.session06.q8_summary
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from .app import app
from .harness import PROMPT, asgi_client, quiet_logs, wired
from .providers import FakeItem, FakeProvider, ProviderError, TextDelta, Usage, fake_script
from .relay import StreamOutcome

FAKE_TEXT = "鶏むね肉とキャベツの塩炒めがおすすめです。"
SCRIPTS: list[list[FakeItem]] = [
    fake_script(FAKE_TEXT, usage=Usage(34, 20)),  # 最後まで届く
    [TextDelta("鶏むね肉とキ"), TextDelta("ャベツの塩炒"), ProviderError("stream_error", provider="fake")],
    [TextDelta("鶏むね肉とキ"), ProviderError("connection", provider="fake")],
]


def pad(tokens: int) -> int:
    """見積もりに 1.2 倍の安全係数を掛けて切り上げる（整数だけで計算し、浮動小数の誤差を避ける）。"""
    return (tokens * 6 + 4) // 5


def summarize(outcomes: Iterable[StreamOutcome]) -> dict[str, dict[str, int]]:
    """usage_source（upstream / estimated）ごとの件数とトークン数。estimated には安全係数込みの値も足す。"""
    out: dict[str, dict[str, int]] = {}
    for o in outcomes:
        if o.usage is None or o.usage_source is None:
            continue  # relay_chat() の finally を通れば必ず入る。入っていないものは数えない
        row = out.setdefault(o.usage_source, {"count": 0, "input_tokens": 0, "output_tokens": 0})
        row["count"] += 1
        row["input_tokens"] += o.usage.input_tokens
        row["output_tokens"] += o.usage.output_tokens
    if "estimated" in out:
        est = out["estimated"]
        est["padded_input_tokens"] = pad(est["input_tokens"])
        est["padded_output_tokens"] = pad(est["output_tokens"])
    return out


async def run_scripts() -> list[StreamOutcome]:
    """3つの台本を順に流し、増えた結末だけを返す。"""
    before = len(app.state.outcomes)
    for script in SCRIPTS:
        async with wired(app, FakeProvider(script)), asgi_client(app) as c:
            await c.post("/api/chat/stream", json={"message": PROMPT})
    return list(app.state.outcomes)[before:]


async def main() -> None:
    quiet_logs()  # 失敗のログ（request_id 入り）を画面に出さない
    outcomes = await run_scripts()
    print([o.reason for o in outcomes])
    print(summarize(outcomes))


if __name__ == "__main__":
    asyncio.run(main())
