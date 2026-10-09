"""復習4（セッション2〜16の横断復習）の検証。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/review04

上流は FakeProvider・止まったままの上流（StallingProvider）・カセットの再生。録画（問題5・7）のときだけ mockllm を呼ぶ
（課金なし）。時計は FixedClock、待ちは FakeSleep。DB はスキーマ review04、Redis は接頭辞 review04: だけを初期化する。
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import tempfile
from contextlib import aclosing
from pathlib import Path

from kondate.clock import FixedClock
from kondate.db import SessionLocal, engine
from kondate.verifykit import check, eq, finish
from src.review04.app import create_app
from src.review04.breaker import PREFIX
from src.review04.cassette import CassetteMismatch, load_cassette
from src.review04.fallback import Route
from src.review04.harness import (CHAT, LIGHT, BrokenFactory, LogBuffer, StallingProvider, clear_events, clear_redis,
                                  client_for, dbcheck, mock_stats, prepare_db, redis_client, reset_mock, rows, shape,
                                  sse_names, usd)
from src.review04.lifecycle import Drain
from src.review04.metering import Meter, metered, save_usage
from src.review04.middleware import REQUEST_ID_RE
from src.review04.pricing import PRICES_PATH, cost_usd, load_price_table
from src.review04.providers import FakeProvider, ProviderError, Usage, fake_script
from src.review04.q1_audit import LedgerRow, audit, backfill_records
from src.review04.q2_startup import check_or_exit, startup_problems
from src.review04.q5_replay import PROMPT, record_fallback, replay_fallback, replay_routes
from src.review04.relay import StreamOutcome, chat_for, estimate_input_tokens, prime, relay

LOGS = LogBuffer()  # app を import した後に作る（create_app() が付けた標準出力の JSON 出力を置き換える）
TABLE = load_price_table()
T0 = FixedClock().now()  # 2026-10-02 18:00 JST
FAKE_TEXT = "鶏むね肉とキャベツの塩炒めがおすすめです。"  # 21文字 → 6文字ずつ4つの delta
STALL_TEXTS = ["鶏むね肉とキ", "ャベツの塩炒"]  # 2つ送って黙る（36バイト → 見積もり 12 トークン）
SAME = "req_01K6H8M3Q4RZ5T7V9W1X3Y5Z7F"  # 同じ値を送り続けるクライアント（問題6）
TABLE_SQL = ("SELECT request_id, usage_source, outcome, input_tokens, output_tokens, cost_usd "
             "FROM review04.usage_events ORDER BY request_id")

# ---------------------------------------------------------------- 問題1の材料（問題文に載せたものと同じ）
SAMPLE_LINES = [
    "INFO:     Started server process [8]",
    '{"ts": "2026-10-02T18:00:03.512+09:00", "level": "INFO", "logger": "kondate.review04.relay", "event": "stream_closed", "request_id": "req_01K6H8M3Q4RZ5T7V9W1X3Y5Z7A", "reason": "completed", "error_type": null, "deltas": 32, "usage_source": "upstream", "input_tokens": 34, "output_tokens": 181}',
    '{"ts": "2026-10-02T18:00:05.004+09:00", "level": "WARNING", "logger": "kondate.review04.lifecycle", "event": "drain_started", "grace_seconds": 5}',
    '{"ts": "2026-10-02T18:00:10.006+09:00", "level": "INFO", "logger": "kondate.review04.relay", "event": "stream_closed", "request_id": "req_01K6H8M3Q4RZ5T7V9W1X3Y5Z7B", "reason": "drained", "error_type": "service_unavailable", "deltas": 2, "usage_source": "estimated", "input_tokens": 34, "output_tokens": 12}',
    '{"ts": "2026-10-02T18:00:10.021+09:00", "level": "INFO", "logger": "kondate.review04.relay", "event": "stream_closed", "request_id": "req_01K6H8M3Q4RZ5T7V9W1X3Y5Z7C", "reason": "failed", "error_type": "upstream_unavailable", "deltas": 2, "usage_source": "estimated", "input_tokens": 34, "output_tokens": 12}',
    '{"ts": "2026-10-02T18:00:10.034+09:00", "level": "ERROR", "logger": "kondate.review04.metering", "event": "usage_record_failed", "request_id": "req_01K6H8M3Q4RZ5T7V9W1X3Y5Z7C", "user_id": "u001", "model": "claude-sonnet-5-5", "started_at": "2026-10-02T18:00:09+09:00", "input_tokens": 34, "output_tokens": 12, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "usage_source": "estimated", "outcome": "failed", "exc_type": "ConnectionRefusedError", "exc": "Traceback (most recent call last): ..."}',
    '{"ts": "2026-10-02T18:00:10.120+09:00", "level": "INFO", "logger": "kondate.review04.relay", "event": "stream_closed", "request_id": "req_01K6H8M3Q4RZ5T7V9W1X3Y5Z7D", "reason": "cancelled", "error_type": null, "deltas": 1, "usage_source": "estimated", "input_tokens": 34, "output_tokens": 6}',
    '{"ts": "2026-10-02T18:00:10.2',
]
SAMPLE_LEDGER = [
    LedgerRow("req_01K6H8M3Q4RZ5T7V9W1X3Y5Z7A", "upstream", "completed", 34, 181),
    LedgerRow("req_01K6H8M3Q4RZ5T7V9W1X3Y5Z7B", "estimated", "cancelled", 34, 12),
    LedgerRow("req_01K6H8M3Q4RZ5T7V9W1X3Y5Z7D", "estimated", "cancelled", 34, 6),
    LedgerRow("req_01K6H8M3Q4RZ5T7V9W1X3Y5Z7E", "upstream", "completed", 120, 300),
]


def fake_ok() -> FakeProvider:
    return FakeProvider(fake_script(FAKE_TEXT, usage=Usage(34, 20)))


def e529() -> ProviderError:
    return ProviderError("overloaded", provider="fake", status_code=529)


def meter(factory=SessionLocal) -> Meter:
    return Meter(factory, TABLE, "u001", CHAT, T0)


async def stalled(request_id: str) -> tuple[object, StreamOutcome]:
    chat = chat_for(PROMPT)
    primed = await prime(StallingProvider(STALL_TEXTS), chat)
    return primed, StreamOutcome(request_id, "m1", input_estimate=estimate_input_tokens(chat))


async def drive(gen, drain: Drain | None = None, *, begin_after: int = 3) -> list:
    """SSE のイベントを最後まで読む。drain を渡すと、begin_after 件目を受け取った所で店じまいを始める。"""
    got = []
    async with aclosing(gen):
        async for ev in gen:
            got.append(ev)
            if drain is not None and len(got) == begin_after:
                drain.begin()
    return got


def closed_lines(request_id: str) -> list[tuple]:
    return [(d["reason"], d["usage_source"], d["input_tokens"], d["output_tokens"])
            for d in LOGS.events("stream_closed") if d["request_id"] == request_id]


async def _setup() -> None:
    try:
        await prepare_db()
    finally:
        await engine.dispose()


asyncio.run(_setup())


@dbcheck("V1 問題1：ログと台帳を request_id で突き合わせ、推定値の行と記録漏れを挙げる。記録漏れはログから足し直す")
async def _():
    await clear_events()
    found = audit(SAMPLE_LINES, SAMPLE_LEDGER)
    eq([(f.request_id[-2:], f.kind, f.reason, f.input_tokens, f.output_tokens) for f in found],
       [("7B", "estimated", "drained", 34, 12), ("7C", "missing", "failed", 34, 12),
        ("7D", "estimated", "cancelled", 34, 6)], "突き合わせ")
    records = backfill_records(SAMPLE_LINES)
    eq(len(records), 1, "足し直す記録")
    first = await save_usage(SessionLocal, records[0], TABLE)
    again = await save_usage(SessionLocal, records[0], TABLE)
    got = [(rid[-2:], src, out, i, o, usd(c)) for rid, src, out, i, o, c in await rows(TABLE_SQL)]
    eq((first, again), (True, False), "足し直しを2回")
    eq(got, [("7C", "estimated", "failed", 34, 12, "0.00018800")], "台帳")
    return ("推定値の行 7B（drained）・7D（cancelled）／記録漏れ 7C（failed・34／12）／"
            "足し直しは1回目 True・2回目 False で1行・0.00018800")


@check("V2 問題2：単価表とモデルの設定を起動前に突き合わせ、足りなければ理由を並べて exit 1")
def _():
    models = {"LLM_MODEL": CHAT, "LLM_MODEL_LIGHT": LIGHT}
    good = startup_problems(models, PRICES_PATH, T0)
    missing = startup_problems({**models, "LLM_MODEL_LIGHT": "kondate-test-model"}, PRICES_PATH, T0)
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "prices.json"
        row = {"model": "kondate-test-model", "effective_from": "2026-10-02",
               "input": 1.0, "output": "5.00", "cache_write": "1.25", "cache_read": "0.10"}
        path.write_text(json.dumps({"source": "x", "checked_on": "2026-10-02", "prices": [row]}), encoding="utf-8")
        number = startup_problems(models, path, T0)
        path.write_text("{", encoding="utf-8")
        broken = startup_problems(models, path, T0)
        path.write_text(json.dumps({"source": "x", "prices": []}), encoding="utf-8")
        no_key = startup_problems(models, path, T0)
        no_file = startup_problems(models, Path(d) / "none.json", T0)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        try:
            check_or_exit({**models, "LLM_MODEL_LIGHT": "kondate-test-model"}, PRICES_PATH, T0)
            code = 0
        except SystemExit as e:
            code = e.code
    light_line = "- LLM_MODEL_LIGHT: 単価表にありません（kondate-test-model・2026-10-02 時点）"
    eq(good, [], "そろっている")
    eq(missing, [light_line], "単価表に無いモデル")
    eq(number, ["- PRICES: kondate-test-model の input: 単価は文字列で書いてください（1.0）"], "単価が数値")
    eq((broken, no_key, no_file), (["- PRICES: 単価表が JSON として読めません"],
                                   ["- PRICES: 単価表に項目 checked_on がありません"],
                                   ["- PRICES: 単価表のファイルを読めません"]), "読めない単価表")
    eq((code, err.getvalue().splitlines()), (1, ["設定エラー：起動を中止します（1 件）", light_line]), "exit 1")
    return ("そろっていれば問題なし／単価表に無いモデル・数値の単価・壊れた JSON・項目の欠け・ファイルなしを1行ずつ"
            "／check_or_exit は exit 1")


@dbcheck("V3 問題3：異常系の表（開始前に全経路が失敗・drain 中の新規・台帳に書けない）")
async def _():
    await clear_redis()
    await clear_events()
    LOGS.clear()
    app = create_app(configure_logging=False)
    routes = [Route("primary", FakeProvider([e529()]), CHAT), Route("light", FakeProvider([e529()]), LIGHT)]
    async with client_for(app, routes, clock=FixedClock()) as c:
        down = await c.post("/api/chat/stream", json={"message": PROMPT})
    fresh = fake_ok()
    app = create_app(configure_logging=False)
    async with client_for(app, [Route("primary", fresh, CHAT)], clock=FixedClock()) as c:
        app.state.drain.begin()
        refused = await c.post("/api/chat/stream", json={"message": PROMPT})
        app.state.drain.cancel_timer()
    chat = chat_for(PROMPT)
    outcome = StreamOutcome("req_v3_db", "m1", input_estimate=estimate_input_tokens(chat))
    got = await drive(metered(relay(await prime(fake_ok(), chat), outcome=outcome, drain=Drain(5)), outcome,
                              meter(BrokenFactory())))
    failures = [x["request_id"] for x in LOGS.events("usage_record_failed")]
    eq((down.status_code, down.json()["error"]["type"], down.headers["content-type"]),
       (503, "upstream_unavailable", "application/json"), "開始前に全経路が失敗")
    eq((refused.status_code, refused.json()["error"]["type"], refused.headers.get("retry-after"), len(fresh.requests)),
       (503, "service_unavailable", "1", 0), "drain 中の新規")
    eq(shape([e.event for e in got]), "start → delta×4 → usage → done", "台帳に書けないときのイベント")
    eq(failures, ["req_v3_db", "req_v3_db"], "usage_record_failed の行")
    eq(await rows("SELECT count(*) FROM review04.usage_events"), [(0,)], "台帳の行数")
    return ("全経路 529 → 503 upstream_unavailable（JSON）／drain 中の新規 → 503 service_unavailable・retry-after: 1・"
            "上流 0 回／台帳に書けない → usage と done は届き、usage_record_failed が2行・台帳は 0 行（3つとも）")


@dbcheck("V4 問題4（直す前）：中継だけでは、drain の締め切りで閉じたストリームが台帳に残らない")
async def _():
    await clear_events()
    LOGS.clear()
    drain = Drain(0.05)
    primed, outcome = await stalled("req_v4")
    got = await drive(relay(primed, outcome=outcome, drain=drain), drain)
    eq([e.event for e in got], ["start", "delta", "delta", "error"], "イベント")
    eq(json.loads(got[-1].raw_data)["type"], "service_unavailable", "error.type")
    eq(closed_lines("req_v4"), [("drained", "estimated", 34, 12)], "stream_closed の行")
    eq(await rows("SELECT count(*) FROM review04.usage_events"), [(0,)], "台帳の行数")
    return "start → delta×2 → error（service_unavailable）・ログには drained / estimated 34／12・台帳は 0 行"


@dbcheck("V5 問題4：metered で包むと、drain で閉じたストリームも見積もりで1行（outcome は cancelled）")
async def _():
    await clear_events()
    LOGS.clear()
    drain = Drain(0.05)
    primed, outcome = await stalled("req_v5")
    got = await drive(metered(relay(primed, outcome=outcome, drain=drain), outcome, meter()), drain)
    ledger = [(rid, src, out, i, o, usd(c)) for rid, src, out, i, o, c in await rows(TABLE_SQL)]
    eq([e.event for e in got], ["start", "delta", "delta", "error"], "イベント")
    eq(ledger, [("req_v5", "estimated", "cancelled", 34, 12, "0.00018800")], "台帳")
    eq(closed_lines("req_v5"), [("drained", "estimated", 34, 12)], "stream_closed の行")
    return "start → delta×2 → error・台帳 estimated / cancelled 34／12・0.00018800・ログの reason は drained"


@dbcheck("V6 問題4：完了は usage を送る前に記録・猶予切れの取り消しでも1行・途中の失敗も1行")
async def _():
    await clear_events()
    LOGS.clear()
    chat = chat_for(PROMPT)
    # 完了：usage を受け取った時点で、もう台帳にある
    outcome = StreamOutcome("req_v6_done", "m1", input_estimate=estimate_input_tokens(chat))
    gen = metered(relay(await prime(fake_ok(), chat), outcome=outcome, drain=Drain(5)), outcome, meter())
    at_usage = None
    async with aclosing(gen):
        async for ev in gen:
            if ev.event == "usage":
                at_usage = await rows("SELECT count(*) FROM review04.usage_events")
    # 取り消し：uvicorn の猶予（GRACEFUL_TIMEOUT_SECONDS）が切れて、タスクごと止められた
    primed, cut = await stalled("req_v6_cut")
    gen = metered(relay(primed, outcome=cut, drain=Drain(5)), cut, meter())
    names: list[str] = []
    reached = asyncio.Event()

    async def consume() -> None:
        async for ev in gen:
            names.append(ev.event)
            if len(names) == 3:
                reached.set()

    task = asyncio.create_task(consume())
    await reached.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    # 途中の失敗：delta 2つのあと、上流から error イベント（HTTP 200 のまま）
    failing = FakeProvider([*fake_script(FAKE_TEXT)[:2], ProviderError("stream_error", provider="fake", status_code=200)])
    failed = StreamOutcome("req_v6_fail", "m1", input_estimate=estimate_input_tokens(chat))
    got = await drive(metered(relay(await prime(failing, chat), outcome=failed, drain=Drain(5)), failed, meter()))
    ledger = [(rid, src, out, i, o, usd(c)) for rid, src, out, i, o, c in await rows(TABLE_SQL)]
    eq(at_usage, [(1,)], "usage を受け取った時点の行数")
    eq((names, task.cancelled()), (["start", "delta", "delta"], True), "取り消したストリーム")
    eq(([e.event for e in got], json.loads(got[-1].raw_data)["type"]),
       (["start", "delta", "delta", "error"], "upstream_error"), "途中の失敗")
    eq(ledger, [("req_v6_cut", "estimated", "cancelled", 34, 12, "0.00018800"),
                ("req_v6_done", "upstream", "completed", 34, 20, "0.00026800"),
                ("req_v6_fail", "estimated", "failed", 34, 12, "0.00018800")], "台帳")
    return ("完了は usage の時点で1行（upstream 34／20・0.00026800）／取り消しは estimated / cancelled 34／12／"
            "途中の失敗は error（upstream_error）・estimated / failed 34／12")


@check("V7 問題5：mockllm から録った「primary は 529・light は正常」を再生すると、同じ経路・同じ待ち時間で、mockllm を呼ばない")
async def _():
    await clear_redis()
    await reset_mock()
    with tempfile.TemporaryDirectory() as d:
        async with redis_client() as redis:
            recorded = await record_fallback(Path(d), redis)
            counts = (len(load_cassette(Path(d) / "primary.jsonl")), len(load_cassette(Path(d) / "light.jsonl")))
            after_record = await mock_stats()
            await clear_redis()
            replayed = await replay_fallback(Path(d), redis)
            breaker = await redis.hgetall(f"{PREFIX}:cb:primary")
            after_replay = await mock_stats()
    attempts = [("primary", 1, "overloaded", 0.0), ("primary", 2, "overloaded", 0.25), ("light", 1, "ok", 0.0)]
    eq(replayed, recorded, "録画と再生の結果")
    eq((recorded.route, recorded.fallback, recorded.attempts, recorded.sleeps),
       ("light", "light", attempts, [0.25]), "経路・試行・待ち")
    eq((recorded.deltas, recorded.usage), (32, Usage(34, 181)), "light の応答")
    eq(counts, (2, 1), "カセットの行数（primary・light）")
    eq((after_record["total"], after_record["by_status"]), (3, {"529": 2, "200": 1}), "録画で mockllm に届いた要求")
    eq(after_replay["total"], 3, "再生のあとも増えない")
    eq((breaker["state"], breaker["failures"]), ("closed", "2"), "primary のブレーカ")
    return ("primary 529×2（待ち 0.25 秒）→ light で delta 32・usage 34／181／カセット 2行・1行／"
            "mockllm には録画の 3 回だけ（529×2・200×1）／primary のブレーカは closed・連続失敗 2")


@check("V8 問題5：経路のモデルを変えると、再生は CassetteMismatch で止まる（黙って古い応答を返さない）")
async def _():
    await clear_redis()
    with tempfile.TemporaryDirectory() as d:
        async with redis_client() as redis:
            await record_fallback(Path(d), redis)
            await clear_redis()
            try:
                await replay_fallback(Path(d), redis, light_model="kondate-test-model")
                raise AssertionError("録画と違う要求が通った")
            except CassetteMismatch as e:
                message = str(e)
    eq(message, "1 件目の要求が録画と違います（違う項目：model）。意図した変更なら record_fallback() で録り直してください",
       "メッセージ")
    return "light の 1 件目で CassetteMismatch（違う項目：model）"


@dbcheck("V9 問題6（直す前）：受け取った x-request-id を台帳のキーにすると、同じ ID の2回目の usage が黙って消える")
async def _():
    await clear_redis()
    await clear_events()
    LOGS.clear()
    app = create_app(trust_incoming=True, configure_logging=False)
    async with client_for(app, [Route("primary", fake_ok(), CHAT)], clock=FixedClock()) as c:
        r1 = await c.post("/api/chat/stream", json={"message": PROMPT}, headers={"x-request-id": SAME})
        r2 = await c.post("/api/chat/stream", json={"message": PROMPT}, headers={"x-request-id": SAME})
    eq((r1.status_code, r2.status_code), (200, 200), "status")
    eq((r1.headers["x-request-id"], r2.headers["x-request-id"]), (SAME, SAME), "応答の x-request-id")
    eq([shape(sse_names(r.text)) for r in (r1, r2)], ["start → delta×4 → usage → done"] * 2, "SSE")
    eq(await rows("SELECT count(*) FROM review04.usage_events"), [(1,)], "台帳の行数")
    eq(LOGS.events("usage_record_failed"), [], "失敗のログ")
    return "2回とも 200・usage まで届く／台帳は1行（2回目は ON CONFLICT で黙って捨てられ、失敗のログも出ない）"


@dbcheck("V10 問題6：request_id は毎回採番し、受け取った値は client_request_id としてログにだけ残す")
async def _():
    await clear_redis()
    await clear_events()
    LOGS.clear()
    app = create_app(configure_logging=False)
    async with client_for(app, [Route("primary", fake_ok(), CHAT)], clock=FixedClock()) as c:
        sent = [SAME, SAME, "req_abc<script>"]
        rs = [await c.post("/api/chat/stream", json={"message": PROMPT}, headers={"x-request-id": h}) for h in sent]
    ids = [r.headers["x-request-id"] for r in rs]
    ledger = sorted(r[0] for r in await rows("SELECT request_id FROM review04.usage_events"))
    finished = [d for d in LOGS.events("request_finished") if d["path"] == "/api/chat/stream"]
    assert all(REQUEST_ID_RE.fullmatch(i) for i in ids), ids
    eq((len(set(ids)), SAME in ids), (3, False), "応答の x-request-id（3つとも別・受け取った値ではない）")
    eq(ledger, sorted(ids), "台帳の request_id")
    eq([(d["request_id"], d.get("client_request_id")) for d in finished],
       [(ids[0], SAME), (ids[1], SAME), (ids[2], None)], "request_finished の行")
    return ("3回とも別の request_id を採番・台帳は3行／request_finished に client_request_id（同じ値が2行）、"
            "形の悪い値は残さない")


@dbcheck("V11 問題7：フォールバックした要求は、答えた経路のモデルと単価で台帳に載り、ヘッダ・ログ・台帳が同じ request_id でつながる")
async def _():
    await clear_redis()
    await clear_events()
    with tempfile.TemporaryDirectory() as d:
        async with redis_client() as redis:
            await record_fallback(Path(d), redis)
        routes = replay_routes(Path(d))
    await clear_redis()
    LOGS.clear()
    app = create_app(configure_logging=False)
    async with client_for(app, routes, clock=FixedClock()) as c:
        r = await c.post("/api/chat/stream", json={"message": PROMPT})
    rid = r.headers["x-request-id"]
    ledger = [(x, m, src, out, i, o, usd(cost)) for x, m, src, out, i, o, cost in await rows(
        "SELECT request_id, model, usage_source, outcome, input_tokens, output_tokens, cost_usd "
        "FROM review04.usage_events")]
    eq((r.status_code, r.headers.get("x-kondate-fallback")), (200, "light"), "status とフォールバックのヘッダ")
    eq(shape(sse_names(r.text)), "start → delta×32 → usage → done", "SSE")
    eq(ledger, [(rid, LIGHT, "upstream", "completed", 34, 181, "0.00093900")], "台帳")
    eq([(x["route"], x["reason"], x["attempts"], x["request_id"]) for x in LOGS.events("fallback")],
       [("light", "overloaded", 3, rid)], "fallback の行")
    eq([(x["request_id"], x["reason"], x["usage_source"]) for x in LOGS.events("stream_closed")],
       [(rid, "completed", "upstream")], "stream_closed の行")
    wrong = usd(cost_usd(Usage(34, 181), TABLE.price_for(CHAT, T0)))
    eq(wrong, "0.00187800", "LLM_MODEL の単価で計算した場合")
    return ("200・x-kondate-fallback: light・start → delta×32 → usage → done／台帳は LLM_MODEL_LIGHT・34／181・"
            "0.00093900（LLM_MODEL の単価なら 0.00187800）／fallback・stream_closed・台帳の request_id が応答ヘッダと一致")


finish("review04")
