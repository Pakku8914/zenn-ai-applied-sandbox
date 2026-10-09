"""Session 6 の練習問題の解答を検査する。

    docker compose exec api python src/session06/verify_practice.py
"""

from __future__ import annotations

import asyncio

import httpx2
from uuid_utils import uuid7

from kondate.cache import make_redis
from kondate.verifykit import check, eq, finish, sse_events
from src.session06 import (q1_boundary, q2_classify, q3_replay, q4_estimate, q5_nobuffer, q6_grace, q7_contract,
                           q8_summary, q9_inspect, q10_audit, q11_client, q12_streams)
from src.session06.app import app as main_app
from src.session06.faults import FAULTS, raw_fault
from src.session06.harness import PROMPT, asgi_client, clear_keys, mock_provider, quiet_logs, read_stream, serve, shape, wired
from src.session06.providers import FakeProvider, Usage, fake_script
from src.session06.resume import EventLog, load_replay
from src.session06.sse import sse_event

FAKE_TEXT = "鶏むね肉とキャベツの塩炒めがおすすめです。"
LOGS = quiet_logs()
asyncio.run(clear_keys())


@check("Q1 失敗の位置で応答の形が変わる（最初のイベントの前は JSON、あとは error イベント）")
async def _():
    got = {name: await q1_boundary.observe(script) for name, script in q1_boundary.CASES.items()}
    eq(got, {
        "位置0": (503, "upstream_unavailable（JSON）"),
        "位置1": (200, "start → delta → error（upstream_unavailable）"),
        "位置2": (200, "start → delta×2 → error（upstream_error）"),
    }, "位置ごとの応答")
    return ("位置0 → 503 upstream_unavailable（JSON）・位置1 → 200 start → delta → error（upstream_unavailable）・"
            "位置2 → 200 start → delta×2 → error（upstream_error）")


@check("Q2 生の例外を4つに分類する")
async def _():
    got = {f: q2_classify.classify((await raw_fault(f)).error) for f in FAULTS}
    got["RuntimeError"] = q2_classify.classify(RuntimeError("x"))
    eq(got, {"429": "before_start", "529": "before_start", "sse-error": "mid_error",
             "disconnect": "mid_disconnect", "RuntimeError": "other"}, "分類")
    return "429・529 → before_start・sse-error → mid_error・disconnect → mid_disconnect・RuntimeError → other"


@check("Q3 replay_slice：Last-Event-ID の9ケース")
def _():
    entries = [{"id": str(i), "event": "delta", "data": "{}"} for i in range(1, 8)]
    got = {}
    for raw in [None, "", "0", "3", "7", "99", "３", "-1", "abc"]:
        try:
            got[raw] = [e["id"] for e in q3_replay.replay_slice(entries, raw)]
        except ValueError:
            got[raw] = "ValueError"
    all_ids = [str(i) for i in range(1, 8)]
    eq(got, {None: all_ids, "": all_ids, "0": all_ids, "3": ["4", "5", "6", "7"], "7": [],
             "99": "ValueError", "３": "ValueError", "-1": "ValueError", "abc": "ValueError"}, "ケースごとの結果")
    return "None・空・0 → 7件・3 → 4件・7 → 0件・99・全角の３・-1・abc → ValueError"


@check("Q4 入力トークンの見積もりが mockllm の count_tokens と一致する")
async def _():
    got = {}
    for name, chat in q4_estimate.CASES.items():
        estimated, counted = q4_estimate.estimate_input_tokens_full(chat), await q4_estimate.count_tokens(chat)
        eq(estimated, counted, f"{name}：見積もりと count_tokens")
        got[name] = counted
    eq(got, {"単発": 34, "system 付き": 55, "3件の会話": 67}, "count_tokens の値")
    return "単発 34・system 付き 55・3件の会話 67（どれも count_tokens と一致）"


@check("Q5 NoBufferingMiddleware：text/event-stream にだけ X-Accel-Buffering: no を足す")
async def _():
    async with asgi_client(q5_nobuffer.app) as c:
        ticks, buffered, health = await c.get("/ticks"), await c.get("/ticks-buffered"), await c.get("/health")
    eq((ticks.headers.get("x-accel-buffering"), buffered.headers.get("x-accel-buffering"),
        health.headers.get("x-accel-buffering")), ("no", "yes", None), "ヘッダ")
    return "/ticks → no・明示した yes は残す・/health（JSON）→ 付けない"


@check("Q6 猶予つき先読み：TTFT が長くても start はすぐ届き、429 は JSON のまま")
async def _():
    slow = {"x-mock-ttft-ms": "1500"}
    async with mock_provider(headers=slow) as p, wired(q6_grace.app, p), serve(q6_grace.app, 18717) as url:
        async with httpx2.AsyncClient(timeout=60) as c:
            grace = await read_stream(c, "POST", f"{url}/api/chat/stream", {"message": PROMPT})
    async with mock_provider(headers=slow) as p, wired(main_app, p), serve(main_app, 18718) as url:
        async with httpx2.AsyncClient(timeout=60) as c:
            plain = await read_stream(c, "POST", f"{url}/api/chat/stream", {"message": PROMPT})
    async with mock_provider(headers={"x-mock-fault": "429"}) as p, wired(q6_grace.app, p), \
            asgi_client(q6_grace.app) as c:
        limited = await c.post("/api/chat/stream", json={"message": PROMPT})
    async with mock_provider(headers={**slow, "x-mock-fault": "sse-error"}) as p, wired(q6_grace.app, p), \
            asgi_client(q6_grace.app) as c:
        late = await c.post("/api/chat/stream", json={"message": PROMPT})
    names = grace.names()
    assert names[0] == "start" and names[-1] == "done", names
    assert grace.at[0] < 1.0, f"猶予つき：start まで {grace.at[0]:.3f} 秒"
    assert grace.at[names.index("delta")] >= 1.5, f"猶予つき：最初の delta まで {grace.at[names.index('delta')]:.3f} 秒"
    assert plain.at[0] >= 1.5, f"本文の版：start まで {plain.at[0]:.3f} 秒"
    eq((limited.status_code, limited.json()["error"]["type"]), (429, "rate_limited"), "429")
    late_events = sse_events(late.text.split("\n"))
    eq((shape([e["event"] for e in late_events]), late_events[-1]["data"]["type"]),
       ("start → delta×2 → error", "upstream_error"), "猶予のあとの失敗")
    return ("猶予 0.3 秒：start は 1.0 秒未満・最初の delta は 1.5 秒以上あと（本文の版は start も 1.5 秒以上あと）・"
            "429 → JSON 429・猶予のあとの sse-error → start → delta×2 → error（upstream_error）")


# ---------------------------------------------------------------- 分割（前半・後半）で足した問題


@check("Q7 contract_violations：本物のストリームは契約どおり、手で崩した3本は違反を指摘する")
async def _():
    async with mock_provider() as p, wired(main_app, p), asgi_client(main_app) as c:
        failed = await c.post("/api/s06/fault/sse-error", json={"message": PROMPT})
    fake = FakeProvider(fake_script(FAKE_TEXT, usage=Usage(34, 20)))
    async with wired(main_app, fake), asgi_client(main_app) as c:
        completed = await c.post("/api/chat/stream", json={"message": PROMPT})
    for r in (failed, completed):
        eq(q7_contract.contract_violations(sse_events(r.text.split("\n")), r.headers["x-request-id"]), [],
           "アプリが送ったストリーム")
    got = {name: q7_contract.contract_violations(events, q7_contract.RID)
           for name, events in q7_contract.BAD_CASES.items()}
    eq(got, {
        "error のあとに done": ["done か error のどちらか1つで終わっていない"],
        "上流の文をそのまま出した": ["error の message が固定文ではない"],
        "usage のあとに error": ["error の request_id が x-request-id と違う", "error で終わるのに usage を送っている"],
    }, "崩したストリーム")
    return ("sse-error・最後まで届いた回答 → 違反なし・error のあとに done → 終わり方・上流の文 → 固定文ではない・"
            "usage のあとに error → request_id と usage の2件")


@check("Q8 summarize：結末を usage の出どころごとに集計し、見積もりに安全係数を掛ける")
async def _():
    outcomes = await q8_summary.run_scripts()
    eq([o.reason for o in outcomes], ["completed", "failed", "failed"], "結末")
    eq(q8_summary.summarize(outcomes), {
        "upstream": {"count": 1, "input_tokens": 34, "output_tokens": 20},
        "estimated": {"count": 2, "input_tokens": 68, "output_tokens": 18,
                      "padded_input_tokens": 82, "padded_output_tokens": 22},
    }, "集計")
    return "upstream 1件（34・20）・estimated 2件（68・18、1.2 倍で 82・22）"


@check("Q9 inspect_log：保存の状態から、再送できるかどうかを切り分ける")
async def _():
    fake = FakeProvider(fake_script(FAKE_TEXT, usage=Usage(34, 20)))
    async with wired(main_app, fake) as redis, asgi_client(main_app) as c:
        r = await c.post("/api/chat/stream", json={"message": PROMPT})
        complete_id = sse_events(r.text.split("\n"))[0]["data"]["message_id"]
        partial_id = str(uuid7())
        log = EventLog(redis, partial_id)
        await log.append(sse_event("start", {"message_id": partial_id}))
        await log.append(sse_event("delta", {"text": "鶏むね肉とキ"}))
        got = {name: await q9_inspect.inspect_log(redis, mid)
               for name, mid in [("完了", complete_id), ("途中", partial_id), ("不明", str(uuid7()))]}
    eq(got, {
        "完了": {"count": 7, "last_event": "done", "replayable": True, "ttl_ok": True},
        "途中": {"count": 2, "last_event": "delta", "replayable": False, "ttl_ok": True},
        "不明": {"count": 0, "last_event": None, "replayable": False, "ttl_ok": False},
    }, "保存の状態")
    return "完了 → 7件・done・再送できる・途中 → 2件・delta・再送できない・不明 → 0件・TTL なし"


@check("Q10 audit_sse_headers：プロキシの後ろで流れる SSE のヘッダかを点検する")
async def _():
    fake = FakeProvider(fake_script(FAKE_TEXT, usage=Usage(34, 20)))
    async with wired(main_app, fake), asgi_client(main_app) as c:
        rs = {"ticks": await c.get("/api/s06/ticks"), "ticks?fix=1": await c.get("/api/s06/ticks?fix=1"),
              "chat": await c.post("/api/chat/stream", json={"message": PROMPT}), "health": await c.get("/health")}
    got = {name: q10_audit.audit_sse_headers(r.headers) for name, r in rs.items()}
    eq(got, {
        "ticks": ["x-accel-buffering: no が無い"],
        "ticks?fix=1": [],
        "chat": [],
        "health": ["content-type が text/event-stream ではない", "cache-control に no-cache が無い",
                   "x-accel-buffering: no が無い"],
    }, "点検の結果")
    return "ticks → x-accel-buffering が無い・?fix=1 と /api/chat/stream → 問題なし・/health → 3件"


@check("Q11 read_with_resume：末尾を取りこぼしても、再送で回答が完成する")
async def _():
    fake = FakeProvider(fake_script(FAKE_TEXT, usage=Usage(34, 20)))
    got = {}
    async with wired(main_app, fake), asgi_client(main_app) as c:
        for keep in (1, 3, 7):
            got[keep] = await q11_client.read_with_resume(c, keep)
    expected = (FAKE_TEXT, [str(i) for i in range(1, 8)], "done")
    eq(got, {1: expected, 3: expected, 7: expected}, "受け取った回答")
    eq(q11_client.merge([{"id": "1"}, {"id": "2"}], [{"id": "2"}, {"id": "3"}]), [{"id": "1"}, {"id": "2"}, {"id": "3"}],
       "重なった id を捨てる")
    return "1件・3件・7件のどこで途切れても id 1〜7・done まで・文は元の回答と同じ・重なった id は捨てる"


@check("Q12 Redis Streams 版の保存：リスト版と同じ再送結果になる")
async def _():
    events = [sse_event("start", {"message_id": "m"})]
    events += [sse_event("delta", {"text": FAKE_TEXT[i:i + 6]}) for i in range(0, len(FAKE_TEXT), 6)]
    events += [sse_event("usage", {"input_tokens": 34, "output_tokens": 20}), sse_event("done", {"stop_reason": "end_turn"})]
    redis = make_redis()
    try:
        mid, partial = str(uuid7()), str(uuid7())
        list_log, stream_log = EventLog(redis, mid), q12_streams.StreamsEventLog(redis, mid)
        for ev in events:
            await list_log.append(ev)
            await stream_log.append(ev)
        same = {after: (await load_replay(redis, mid, after)) == (await q12_streams.load_replay_streams(redis, mid, after))
                for after in (0, 3, 7)}
        length = await redis.xlen(q12_streams.stream_key(mid))
        ttl = await redis.ttl(q12_streams.stream_key(mid))
        half = q12_streams.StreamsEventLog(redis, partial)
        for ev in events[:2]:
            await half.append(ev)
        unfinished = await q12_streams.load_replay_streams(redis, partial, 0)
        unknown = await q12_streams.load_replay_streams(redis, str(uuid7()), 0)
        after3 = await q12_streams.load_replay_streams(redis, mid, 3)
    finally:
        await redis.aclose()
    eq(same, {0: True, 3: True, 7: True}, "リスト版との一致")
    eq((length, [e["id"] for e in after3]), (7, ["4", "5", "6", "7"]), "件数と再送の id")
    assert 0 < ttl <= 300, ttl
    eq((unfinished, unknown), (None, None), "途中・不明")
    return "XLEN 7・after 0/3/7 ともリスト版と同じ・after 3 → id 4〜7・途中と不明は None・TTL 300 秒以内"


finish("session06-practice")
