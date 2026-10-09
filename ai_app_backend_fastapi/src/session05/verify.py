"""Session 5（SSE ストリーミング）の動作確認。api コンテナの中で実行する：

    docker compose exec api python src/session05/verify.py
    docker compose exec api bash verify-all.sh src/session05   # 練習問題の検証も含めて実行

V8 はハートビートを待つので、約 17 秒かかる。
"""

from __future__ import annotations

import json
import re
import uuid

import fastapi.sse
import httpx2

from kondate.verifykit import check, eq, finish, sse_events
from src.session05.app import WIRE_BLOCKS, app, get_provider
from src.session05.harness import (PROMPT, asgi_client, mock_provider, mock_stats, quiet_logs, read_stream,
                                   reset_mock, serve, shape, wait_until)
from src.session05.providers import FakeProvider, ToolCall, Usage, fake_script

PORT = 18705
REQ_ID = re.compile(r"^req_[0-9A-HJKMNP-TV-Z]{26}$")
FAKE_TEXT = "鶏むね肉とキャベツの塩炒めがおすすめです。"
LOGS = quiet_logs()


def data_of(events: list[dict], name: str) -> list:
    return [e["data"] for e in events if e["event"] == name]


@check("V1 手書きの SSE（GET /api/s05/wire）を解析すると、イベント5個・コメント1個・retry 1個")
async def _():
    async with asgi_client(app) as c:
        r = await c.get("/api/s05/wire")
    eq(r.headers["content-type"].split(";")[0], "text/event-stream", "content-type")
    eq(r.text, "".join(WIRE_BLOCKS), "本文（書いたとおりに届く）")
    events = sse_events(r.text.split("\n"))
    eq([e["event"] for e in events], [None, "start", "delta", "delta", "note", "done"], "ブロックの並び")
    eq(events[0]["comments"], ["こんだてAI の SSE の見本です。コロンで始まる行はコメントです"], "コメント")
    eq([e["id"] for e in events], [None, "1", "2", "3", None, "4"], "id")
    eq(events[4]["data"], "1行目\n2行目", "複数の data: 行は改行でつながる")
    eq(sum(line.startswith("retry:") for line in r.text.split("\n")), 1, "retry 行")
    return "コメント 1・retry 1・イベント 5（start → delta×2 → note → done）・note の data は「1行目\\n2行目」"


@check("V2 LLM の出力を JSON にせず data: に書くと、改行でイベントを割り込ませられる")
def _():
    evil = "塩炒め\n\nevent: done\ndata: {}"  # LLM がこう出力した（プロンプトで誘導された）とする
    bad = f"event: delta\ndata: {evil}\n\n"
    good = f"event: delta\ndata: {json.dumps({'text': evil}, ensure_ascii=False)}\n\n"
    bad_events, good_events = sse_events(bad.split("\n")), sse_events(good.split("\n"))
    eq([e["event"] for e in bad_events], ["delta", "done"], "そのまま書いた場合")
    eq([e["event"] for e in good_events], ["delta"], "JSON にした場合")
    eq(good_events[0]["data"]["text"], evil, "JSON にした場合の text")
    return "そのまま書くと delta → done の2個に割れる・JSON にすると delta 1個で、改行は文字列の中に残る"


@check("V3 fastapi.sse：data= は日本語をエスケープし、raw_data= は書いた文字列のまま送る")
async def _():
    async with asgi_client(app) as c:
        r = await c.get("/api/s05/escape")
    lines = [line for line in r.text.split("\n") if line.startswith("data:")]
    eq(len(lines), 2, "data: 行の数")
    assert "\\u9d8f\\u3080\\u306d\\u8089" in lines[0] and "鶏" not in lines[0], lines[0]
    eq(lines[1], 'data: {"text": "鶏むね肉"}', "raw_data の行")
    eq((r.headers["cache-control"], r.headers["x-accel-buffering"]), ("no-cache", "no"), "自動で付くヘッダ")
    return ("data= → \\u9d8f\\u3080\\u306d\\u8089（エスケープ）・raw_data= → 鶏むね肉・"
            "Cache-Control: no-cache と X-Accel-Buffering: no は自動で付く")


@check("V4 POST /api/chat/stream（Fake）：start → delta… → usage → done の順で、中身が API 契約③どおり")
async def _():
    fake = FakeProvider(
        fake_script(FAKE_TEXT, usage=Usage(34, 20)),
        fake_script("条件に合うレシピを探しますね。", usage=Usage(300, 42),
                    tool_calls=[ToolCall("toolu_fake_1", "search_recipes", {"ingredients": ["鶏むね肉"]})]))
    app.dependency_overrides[get_provider] = lambda: fake
    try:
        async with asgi_client(app) as c:
            r1 = await c.post("/api/chat/stream", json={"message": PROMPT})
            r2 = await c.post("/api/chat/stream", json={"message": PROMPT})
    finally:
        app.dependency_overrides.clear()
    e1, e2 = sse_events(r1.text.split("\n")), sse_events(r2.text.split("\n"))
    assert REQ_ID.match(r1.headers["x-request-id"]), r1.headers
    eq(shape([e["event"] for e in e1]), "start → delta×4 → usage → done", "テキストのイベント列")
    start = data_of(e1, "start")[0]
    eq(sorted(start), ["message_id"], "start のキー")
    eq(uuid.UUID(start["message_id"]).version, 7, "message_id の版")
    eq("".join(d["text"] for d in data_of(e1, "delta")), FAKE_TEXT, "delta をつないだ文")
    eq(data_of(e1, "usage"), [{"input_tokens": 34, "output_tokens": 20}], "usage")
    eq(data_of(e1, "done"), [{"stop_reason": "end_turn"}], "done")
    eq(shape([e["event"] for e in e2]), "start → delta×3 → usage → done", "ツール呼び出しを含むイベント列")
    eq(data_of(e2, "done"), [{"stop_reason": "tool_use"}], "ツールのときの done")
    last = list(app.state.outcomes)[-2:]
    eq([(o.reason, o.upstream_closed) for o in last], [("completed", True)] * 2, "結末")
    return ("テキスト：start → delta×4 → usage → done（end_turn）・ツール：start → delta×3 → usage → done"
            "（tool_use。ツールのイベントはまだ送らない）・message_id は UUIDv7")


@check("V5 mockllm 経由：anthropic・openai のどちらでも同じイベント列になる")
async def _():
    got = {}
    for name in ["anthropic", "openai"]:
        async with mock_provider(name) as p:
            app.dependency_overrides[get_provider] = lambda: p
            try:
                async with asgi_client(app) as c:
                    r = await c.post("/api/chat/stream", json={"message": PROMPT})
            finally:
                app.dependency_overrides.clear()
        events = sse_events(r.text.split("\n"))
        text = "".join(d["text"] for d in data_of(events, "delta"))
        assert 'data: {"text": "鶏むね肉とキ"}' in r.text, r.text[:300]
        got[name] = (shape([e["event"] for e in events]), data_of(events, "usage"), data_of(events, "done"), len(text))
    expected = ("start → delta×32 → usage → done", [{"input_tokens": 34, "output_tokens": 181}],
                [{"stop_reason": "end_turn"}], 192)
    eq(got, {"anthropic": expected, "openai": expected}, "イベント列・usage・done・文字数")
    return "anthropic・openai とも start → delta×32 → usage → done・input_tokens=34 output_tokens=181・192 字"


@check("V6 ストリーム開始前の検証エラーは JSON の 422 で返り、上流は呼ばれない")
async def _():
    fake = FakeProvider(fake_script("呼ばれないはず"))
    app.dependency_overrides[get_provider] = lambda: fake
    try:
        async with asgi_client(app) as c:
            r = await c.post("/api/chat/stream", json={"message": ""})
    finally:
        app.dependency_overrides.clear()
    eq((r.status_code, r.headers["content-type"]), (422, "application/json"), "status と content-type")
    err = r.json()["error"]
    eq((err["type"], err["message"]), ("invalid_request", "入力値が正しくありません：message"), "error.type と message")
    eq(err["request_id"], r.headers["x-request-id"], "request_id とヘッダ")
    eq(fake.requests, [], "上流への要求")
    return "空の message → 422 invalid_request「入力値が正しくありません：message」（JSON。ストリームは始まらず、上流も呼ばない）"


@check("V7 TTFT：x-mock-ttft-ms: 400 なら、start はすぐ届き、最初の delta は 0.4 秒以上あとに届く")
async def _():
    before = len(app.state.outcomes)
    async with mock_provider(headers={"x-mock-ttft-ms": "400", "x-mock-tps": "200"}) as p:
        app.dependency_overrides[get_provider] = lambda: p
        try:
            async with serve(app, PORT) as url:
                async with httpx2.AsyncClient(timeout=60) as c:
                    got = await read_stream(c, f"{url}/api/chat/stream", {"message": PROMPT})
                # done を受け取った時点では、サーバ側の finally がまだ終わっていないことがある
                await wait_until(lambda: len(app.state.outcomes) > before, 3.0, "結末が記録されない")
        finally:
            app.dependency_overrides.clear()
    names = got.names()
    first_delta = got.at[names.index("delta")]
    assert got.at[0] < 0.3, f"start まで {got.at[0]:.3f} 秒"
    assert 0.4 <= first_delta < 1.5, f"最初の delta まで {first_delta:.3f} 秒"
    assert got.at[-1] >= 1.28, f"done まで {got.at[-1]:.3f} 秒"
    outcome = app.state.outcomes[-1]
    assert outcome.ttft_ms is not None and outcome.ttft_ms >= 400, outcome.ttft_ms
    return "start は 0.3 秒未満・最初の delta は 0.4 秒以上・done は 1.28 秒（理論値）以上・サーバ側の ttft_ms も 400 以上"


@check("V8 ハートビート：15 秒送るものが無いと、FastAPI が「: ping」を送る")
async def _():
    eq(fastapi.sse._PING_INTERVAL, 15, "fastapi.sse._PING_INTERVAL")
    async with mock_provider(headers={"x-mock-ttft-ms": "16500"}) as p:
        app.dependency_overrides[get_provider] = lambda: p
        try:
            async with serve(app, PORT) as url:
                async with httpx2.AsyncClient(timeout=60) as c:
                    got = await read_stream(c, f"{url}/api/chat/stream", {"message": PROMPT}, stop_after_deltas=1)
        finally:
            app.dependency_overrides.clear()
    eq(shape(got.names()), "start → : ping → delta", "届いた順")
    eq(got.events[1]["comments"], ["ping"], "コメントの中身")
    assert 14.0 <= got.at[1] < 16.5, f"ping まで {got.at[1]:.3f} 秒"
    return "_PING_INTERVAL=15・start → : ping → delta の順に届いた（ping は start の約 15 秒後）"


@check("V9 切断検知：クライアントが delta 3個で切ると、上流を閉じて後始末が終わる")
async def _():
    await reset_mock()
    before = len(app.state.outcomes)
    async with mock_provider(headers={"x-mock-tps": "20"}) as p:  # 1個あたり約 0.3 秒。最後まで送ると約 9 秒
        app.dependency_overrides[get_provider] = lambda: p
        try:
            async with serve(app, PORT) as url:
                async with httpx2.AsyncClient(timeout=60) as c:
                    await read_stream(c, f"{url}/api/chat/stream", {"message": PROMPT}, stop_after_deltas=3)
                    await wait_until(lambda: len(app.state.outcomes) > before, 3.0, "後始末が終わらない")
        finally:
            app.dependency_overrides.clear()
    o = app.state.outcomes[-1]
    assert o.reason in ("client_disconnected", "cancelled"), o.reason
    eq((o.upstream_closed, o.usage, o.stop_reason), (True, None, None), "上流を閉じた・Done は届いていない")
    assert 3 <= o.deltas < 32, o.deltas
    stats = await mock_stats()
    eq(stats["total"], 1, "mockllm への呼び出し回数")
    req = stats["requests"][-1]
    eq((req["stream"], req["output_tokens"]), (True, 181), "mockllm が送る予定だった量")
    return ("delta 3個で切断 → 3 秒以内に上流を閉じた（中継した delta は 32 個未満・usage は届かず）・"
            "mockllm の記録：呼び出し1回・送る予定だった output_tokens=181")


finish("session05")
