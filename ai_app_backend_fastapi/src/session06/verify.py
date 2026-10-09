"""Session 6（ストリーミングの異常系）の動作確認。api コンテナの中で実行する：

    docker compose exec api python src/session06/verify.py
    docker compose exec api bash verify-all.sh src/session06   # 練習問題の検証も含めて実行

nginx を通したバッファリングの確認は proxy_check.py（nginx を起動してから手で実行する）。
"""

from __future__ import annotations

import asyncio
import json
import math

import anthropic
import httpx2
from uuid_utils import uuid7

from kondate.verifykit import check, eq, finish, sse_events
from src.session06.app import app
from src.session06.errors import MESSAGES
from src.session06.faults import FAULTS, raw_fault
from src.session06.harness import (PROMPT, CountingProvider, asgi_client, clear_keys, mock_provider, quiet_logs,
                                   read_stream, serve, shape, wait_until, wired)
from src.session06.providers import ChatRequest, FakeProvider, ProviderError, TextDelta, Usage, fake_script
from src.session06.resume import EventLog, events_key, load_replay
from src.session06.sse import sse_event

PORT = 18706
FAKE_TEXT = "鶏むね肉とキャベツの塩炒めがおすすめです。"
LOGS = quiet_logs()
asyncio.run(clear_keys())


def events_of(text: str) -> list[dict]:
    return sse_events(text.split("\n"))


async def count_keys(redis) -> int:
    return len([k async for k in redis.scan_iter("s06:events:*")])


@check("V1 SDK の生の例外：開始前は create で、開始後は反復の途中で、種類の違う例外が出る")
async def _():
    got = {}
    for fault in FAULTS:
        r = await raw_fault(fault)
        got[fault] = (r.stage, r.label, r.status, r.deltas, isinstance(r.error, anthropic.APIError))
    eq(got, {
        "429": ("create", "anthropic.RateLimitError", 429, 0, True),
        "529": ("create", "anthropic.OverloadedError", 529, 0, True),
        "sse-error": ("stream", "anthropic.APIStatusError", 200, 2, True),
        "disconnect": ("stream", "httpx2.RemoteProtocolError", None, 2, False),
    }, "fault ごとの (stage, 例外, status_code, delta 数, APIError か)")
    return ("429 → create で anthropic.RateLimitError(429)・529 → create で anthropic.OverloadedError(529)・"
            "sse-error → delta 2個のあと anthropic.APIStatusError(200)・"
            "disconnect → delta 2個のあと httpx2.RemoteProtocolError（anthropic.APIError の外）")


@check("V2 差し替え層：anthropic・openai とも同じ ProviderError.kind にそろう")
async def _():
    chat = ChatRequest(messages=[{"role": "user", "content": PROMPT}])
    got = {}
    for name in ["anthropic", "openai"]:
        for fault in FAULTS:
            deltas = 0
            async with mock_provider(name, headers={"x-mock-fault": fault}) as p:
                try:
                    async for ev in p.stream(chat):
                        deltas += isinstance(ev, TextDelta)
                except ProviderError as e:
                    got[(name, fault)] = (e.kind, e.retry_after, deltas)
    expected = {"429": ("rate_limited", 1, 0), "529": ("overloaded", None, 0),
                "sse-error": ("stream_error", None, 2), "disconnect": ("connection", None, 2)}
    eq(got, {(n, f): v for n in ["anthropic", "openai"] for f, v in expected.items()}, "(kind, retry_after, delta 数)")
    return ("429 → rate_limited(retry_after=1)・529 → overloaded・sse-error → stream_error・"
            "disconnect → connection（後ろの2つは delta 2個のあと）")


@check("V3 開始前の失敗（429・529）は JSON のエラー本文で返り、ストリームは始まらない")
async def _():
    async with mock_provider() as p, wired(app, p) as redis, asgi_client(app) as c:
        r429 = await c.post("/api/s06/fault/429", json={"message": PROMPT})
        r529 = await c.post("/api/s06/fault/529", json={"message": PROMPT})
        keys = await count_keys(redis)
    for r in (r429, r529):
        eq(r.headers["content-type"], "application/json", "content-type")
        err = r.json()["error"]
        eq(err["request_id"], r.headers["x-request-id"], "request_id とヘッダ")
        eq(err["message"], MESSAGES[err["type"]], "固定文")
        assert "rate_limit_error" not in r.text and "overloaded_error" not in r.text, r.text
    eq((r429.status_code, r429.json()["error"]["type"], r429.headers["retry-after"]), (429, "rate_limited", "1"), "429")
    eq((r529.status_code, r529.json()["error"]["type"]), (503, "upstream_unavailable"), "529")
    eq(keys, 0, "Redis に保存されたストリーム")
    return "429 → 429 rate_limited（retry-after: 1）・529 → 503 upstream_unavailable・上流の文は含まない・Redis に記録なし"


@check("V4 開始後の失敗は 200 のまま error イベントで終わる（anthropic・openai 共通）")
async def _():
    got = {}
    for name in ["anthropic", "openai"]:
        for fault in ["sse-error", "disconnect"]:
            async with mock_provider(name) as p, wired(app, p), asgi_client(app) as c:
                r = await c.post(f"/api/s06/fault/{fault}", json={"message": PROMPT})
            events = events_of(r.text)
            err = events[-1]["data"]
            eq(err, {"type": err["type"], "message": MESSAGES[err["type"]], "request_id": r.headers["x-request-id"]},
               "error の data")
            got[(name, fault)] = (r.status_code, shape([e["event"] for e in events]), err["type"],
                                  app.state.outcomes[-1].reason)
    expected = {"sse-error": (200, "start → delta×2 → error", "upstream_error", "failed"),
                "disconnect": (200, "start → delta×2 → error", "upstream_unavailable", "failed")}
    eq(got, {(n, f): v for n in ["anthropic", "openai"] for f, v in expected.items()}, "status・イベント列・種別・結末")
    return ("sse-error → start → delta×2 → error（upstream_error）・"
            "disconnect → start → delta×2 → error（upstream_unavailable）・usage と done は送らない")


@check("V5 想定外の例外も error イベント（internal_error）にし、例外の文は出さない")
async def _():
    secret = RuntimeError("postgresql://kondate:kondate@postgres:5432 に接続できません")
    fake = FakeProvider([TextDelta("鶏むね肉とキ"), TextDelta("ャベツの塩炒"), secret])
    async with wired(app, fake), asgi_client(app) as c:
        r = await c.post("/api/chat/stream", json={"message": PROMPT})
    events = events_of(r.text)
    eq(shape([e["event"] for e in events]), "start → delta×2 → error", "イベント列")
    eq(events[-1]["data"]["message"], "サーバー内部でエラーが発生しました", "固定文")
    assert "postgresql" not in r.text, r.text
    o = app.state.outcomes[-1]
    eq((o.reason, o.error_type, o.usage_source, o.usage), ("failed", "internal_error", "estimated", Usage(34, 12)),
       "結末")
    return "start → delta×2 → error（internal_error・固定文）・結末 failed・usage は見積もり input_tokens=34 output_tokens=12"


@check("V6 キャンセル伝播：delta 3個で切ると上流を閉じ、途中までの usage を見積もって残す")
async def _():
    before = len(app.state.outcomes)
    async with mock_provider(headers={"x-mock-tps": "20"}) as p:  # 1個あたり約 0.3 秒。最後まで送ると約 9 秒
        counting = CountingProvider(p)
        async with wired(app, counting) as redis, serve(app, PORT) as url:
            async with httpx2.AsyncClient(timeout=60) as c:
                await read_stream(c, "POST", f"{url}/api/chat/stream", {"message": PROMPT}, stop_after_deltas=3)
            await wait_until(lambda: len(app.state.outcomes) > before, 3.0, "後始末が終わらない")
            o = app.state.outcomes[-1]
            replay = await load_replay(redis, o.message_id, 0)
    assert o.reason in ("client_disconnected", "cancelled"), o.reason
    eq((o.upstream_closed, counting.closed, counting.finished, o.error_type), (True, True, False, None), "上流と error")
    assert o.deltas >= 3 and counting.pulled < 32, (o.deltas, counting.pulled)
    eq((o.usage_source, o.usage.input_tokens), ("estimated", 34), "usage の出どころと入力")
    eq(o.usage.output_tokens, math.ceil(o.output_bytes / 3), "出力の見積もり")
    assert o.usage.output_tokens > 0, o.usage
    eq(replay, None, "途中で終わったストリームの再送")
    return "上流は最後まで読まれず閉じられた・error イベントは送らない・usage は estimated（input_tokens=34）・再送の対象外"


@check("V7 すべてのイベントに id が付き、Redis に TTL 付きで残る")
async def _():
    fake = FakeProvider(fake_script(FAKE_TEXT, usage=Usage(34, 20)))
    async with wired(app, fake) as redis, asgi_client(app) as c:
        r = await c.post("/api/chat/stream", json={"message": PROMPT})
        events = events_of(r.text)
        key = events_key(events[0]["data"]["message_id"])
        stored = [json.loads(x) for x in await redis.lrange(key, 0, -1)]
        ttl = await redis.ttl(key)
    eq(r.headers["x-accel-buffering"], "no", "fastapi.sse が付けるヘッダ")
    eq(shape([e["event"] for e in events]), "start → delta×4 → usage → done", "イベント列")
    eq([e["id"] for e in events], [str(i) for i in range(1, 8)], "id")
    eq([(s["id"], s["event"]) for s in stored], [(e["id"], e["event"]) for e in events], "保存した id と event")
    eq([json.loads(s["data"]) for s in stored], [e["data"] for e in events], "保存した data")
    assert 0 < ttl <= 300, ttl
    return "id 1〜7（start → delta×4 → usage → done）・s06:events:<message_id> に7件・TTL 300 秒以内・最後は done"


@check("V8 Last-Event-ID 以降を再送する（未完了・不明は 204、不正な ID は 422）")
async def _():
    fake = FakeProvider(fake_script(FAKE_TEXT, usage=Usage(34, 20)))
    async with wired(app, fake) as redis, asgi_client(app) as c:
        first = events_of((await c.post("/api/chat/stream", json={"message": PROMPT})).text)
        mid = first[0]["data"]["message_id"]
        after3 = await c.get(f"/api/chat/stream/{mid}", headers={"Last-Event-ID": "3"})
        everything = await c.get(f"/api/chat/stream/{mid}")
        partial = str(uuid7())  # 途中で終わったストリーム（done も error も無い）を作る
        log = EventLog(redis, partial)
        await log.append(sse_event("start", {"message_id": partial}))
        await log.append(sse_event("delta", {"text": "鶏むね肉とキ"}))
        unfinished = await c.get(f"/api/chat/stream/{partial}")
        unknown = await c.get(f"/api/chat/stream/{uuid7()}")
        bad = await c.get(f"/api/chat/stream/{mid}", headers={"Last-Event-ID": "abc"})
    replayed = events_of(after3.text)
    eq((after3.status_code, after3.headers["content-type"].split(";")[0]), (200, "text/event-stream"), "再送の応答")
    eq([e["id"] for e in replayed], ["4", "5", "6", "7"], "再送した id")
    eq([(e["event"], e["data"]) for e in replayed], [(e["event"], e["data"]) for e in first[3:]], "元と同じ中身")
    eq(len(events_of(everything.text)), 7, "ヘッダなしの再送")
    eq((unfinished.status_code, unknown.status_code), (204, 204), "未完了・不明")
    eq((bad.status_code, bad.json()["error"]["type"]), (422, "invalid_request"), "不正な Last-Event-ID")
    return ("Last-Event-ID: 3 → id 4〜7（delta×2 → usage → done）・ヘッダなし → 7件・未完了 → 204・不明 → 204・"
            "abc → 422 invalid_request")


@check("V9 バッファリング対策のヘッダ：fastapi.sse は自動、StreamingResponse は自分で付ける")
async def _():
    async with asgi_client(app) as c:
        plain = await c.get("/api/s06/ticks")
        fixed = await c.get("/api/s06/ticks?fix=1")
    eq("x-accel-buffering" in plain.headers, False, "?fix なし")
    eq(fixed.headers["x-accel-buffering"], "no", "?fix=1")
    eq(shape([e["event"] for e in events_of(plain.text)]), "tick×5", "イベント列")
    return "/api/chat/stream → X-Accel-Buffering: no（自動。V7 で確認）・/api/s06/ticks → なし・?fix=1 → no・tick 5個"


finish("session06")
