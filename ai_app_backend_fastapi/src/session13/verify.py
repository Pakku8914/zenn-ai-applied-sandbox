"""Session 13（トークン課金計測）の動作確認。api コンテナの中で実行する：

    docker compose exec api python src/session13/verify.py
    docker compose exec api bash verify-all.sh src/session13   # 練習問題の検証も含めて実行
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

from kondate.clock import JST, FixedClock
from kondate.db import SessionLocal, engine
from kondate.verifykit import check, eq, finish
from src.session13.aggregate import daily_usage, day_range, tokens_between
from src.session13.app import app
from src.session13.budget import BudgetSettings, estimate_cost
from src.session13.errors import MESSAGES
from src.session13.inputs import get_model
from src.session13.harness import (CACHE_SYSTEM, CHAT, FAKE_TEXT, LIGHT, PROMPT, SHORT_SYSTEM, Connected, bearer,
                                   clear_events, clear_redis, client_for, dbcheck, issue, mock_provider,
                                   prepare_db, redis_client, reset_mock, rows, scalar, usd)
from src.session13.limiter import Limiter
from src.session13.metering import Meter, UsageRecord, metered_events, recompute_costs, save_usage
from src.session13.plans import PlanLimits
from src.session13.pricing import Price, cost_usd, load_price_table
from src.session13.providers import ChatRequest, FakeProvider, ProviderError, Usage, fake_script
from src.session13.ratelimit import reservation_amount
from src.session13.relay import StreamOutcome, estimate_input_tokens, estimate_tokens, prime

TABLE = load_price_table()
FREE = PlanLimits(10, 20_000)
PRO = PlanLimits(60, 200_000)
ASK = {"message": PROMPT}
T0 = FixedClock().now()  # 2026-10-02 18:00 JST
# 練習用の架空の改定（実際の料金ではありません）。11月1日 00:00 JST から効く
REVISION = Price(CHAT, date(2026, 11, 1), Decimal("1.00"), Decimal("5.00"), Decimal("1.25"), Decimal("0.10"))


def fake_ok() -> FakeProvider:
    return FakeProvider(fake_script(FAKE_TEXT, usage=Usage(34, 20)))  # 1回 54 トークン


def chat_request(system: str | None = None) -> ChatRequest:
    return ChatRequest(messages=[{"role": "user", "content": PROMPT}], system=system, max_tokens=1024, model=CHAT)


def rec(request_id: str, user_id: str, at: datetime, usage: Usage) -> UsageRecord:
    return UsageRecord(request_id, user_id, CHAT, at, usage, "upstream", "completed")


async def _setup() -> None:
    try:
        await prepare_db()
    finally:
        await engine.dispose()


asyncio.run(_setup())


@dbcheck("V1 Alembic：スキーマ s13 に users・api_keys・usage_events と版の表を作る")
async def _():
    tables = [r[0] for r in await rows("SELECT table_name FROM information_schema.tables "
                                       "WHERE table_schema = 's13' ORDER BY table_name")]
    eq(tables, ["alembic_version", "api_keys", "usage_events", "users"], "s13 の表")
    eq(await scalar("SELECT version_num FROM s13.alembic_version"), "0002", "版")
    return "s13 に alembic_version・api_keys・usage_events・users（版は 0002。版の表も s13 に置く）"


@check("V2 単価表は日付つきのデータ：記録の時刻（JST の日付）で単価を選ぶ。確認日より前と表に無いモデルは None")
def _():
    eq((TABLE.source, TABLE.checked_on, len(TABLE.rows)),
       ("https://platform.claude.com/docs/en/about-claude/pricing", date(2026, 10, 2), 2), "出典・確認日・行数")
    chat, light = TABLE.price_for(CHAT, T0), TABLE.price_for(LIGHT, T0)
    eq([str(v) for v in (chat.input, chat.output, chat.cache_write, chat.cache_read)],
       ["2.00", "10.00", "2.50", "0.20"], "チャット用")
    eq([str(v) for v in (light.input, light.output, light.cache_write, light.cache_read)],
       ["1.00", "5.00", "1.25", "0.10"], "軽い処理用")
    eq((TABLE.price_for(CHAT, datetime(2026, 10, 1, 23, 59, 59, tzinfo=JST)), TABLE.price_for("unknown-model", T0)),
       (None, None), "確認日より前・表に無いモデル")
    revised = TABLE.with_rows(REVISION)
    before = revised.price_for(CHAT, datetime(2026, 10, 31, 14, 59, 59, tzinfo=timezone.utc))
    after = revised.price_for(CHAT, datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc))
    eq((before.effective_from, after.effective_from), (date(2026, 10, 2), date(2026, 11, 1)), "改定の境目")
    try:
        TABLE.with_rows(replace(REVISION, effective_from=date(2026, 10, 2)))
        raise AssertionError("同じ日付の単価が2つ入った")
    except ValueError:
        pass
    return ("出典 URL・確認日 2026-10-02・2行／チャット用 2.00・10.00・2.50・0.20、軽い処理用 1.00・5.00・1.25・0.10"
            "（USD/100万トークン）／10月1日と表に無いモデルは None／架空の改定は UTC 10月31日 15:00（JST 11月1日 0:00）"
            "から効く／同じモデル・同じ日付の重複は ValueError")


@check("V3 金額は Decimal で 4種のトークン×単価。float は 0.1 を1回ずつ10回足しても 1 にならない")
def _():
    total, exact = 0.0, Decimal(0)
    for _ in range(10):  # 1行ずつ足していく集計と同じ足し方（3.12 の sum() は補正するので使わない）
        total += 0.1
        exact += Decimal("0.1")
    eq(total, 0.9999999999999999, "float の和")
    eq(exact, Decimal("1.0"), "Decimal の和")
    price = TABLE.price_for(CHAT, T0)
    cases = [Usage(34, 20), Usage(34, 181), Usage(30, 181, 0, 1084), Usage(30, 181, 1084, 0), Usage(1114, 181)]
    eq([usd(cost_usd(u, price)) for u in cases],
       ["0.00026800", "0.00187800", "0.00458000", "0.00208680", "0.00403800"], "金額（USD）")
    return ("float で 0.1 を1回ずつ10回足すと 0.9999999999999999・Decimal は 1.0／入力34・出力20 → 0.00026800、"
            "入力34・出力181 → 0.00187800（チャット用の単価）")


@check("V4 キャッシュ（mockllm）：接頭辞 1084 の system を2回送ると、1回目は作成・2回目は読み出し。金額で比べる")
async def _():
    await reset_mock()
    eq((estimate_tokens(CACHE_SYSTEM), estimate_tokens(SHORT_SYSTEM)), (1080, 360), "system のトークン")
    async with mock_provider() as cached, mock_provider(cache_system=False) as plain:
        first = (await cached.complete(chat_request(CACHE_SYSTEM))).usage
        second = (await cached.complete(chat_request(CACHE_SYSTEM))).usage
        nocache = (await plain.complete(chat_request(CACHE_SYSTEM))).usage
        short = (await cached.complete(chat_request(SHORT_SYSTEM))).usage
    eq(first, Usage(30, 181, 0, 1084), "1回目（作成）")
    eq(second, Usage(30, 181, 1084, 0), "2回目（読み出し）")
    eq(nocache, Usage(1114, 181), "cache_control なし")
    eq(short, Usage(394, 181), "接頭辞 364")
    price = TABLE.price_for(CHAT, T0)
    eq([usd(cost_usd(u, price)) for u in (first, second, nocache)], ["0.00458000", "0.00208680", "0.00403800"],
       "金額")
    return ("1回目 入力30・作成1084 → 0.00458000／2回目 入力30・読み出し1084 → 0.00208680／"
            "キャッシュなし 入力1114 → 0.00403800／接頭辞 364 は作成されない（入力 394）")


async def stream_once(provider: FakeProvider, request_id: str, *, cut_after: int | None = None,
                      ) -> tuple[list[str], object]:
    """metered_events を直接回す。usage イベントを受け取った時点の行数も返す。"""
    chat = chat_request()
    async with redis_client() as redis:
        lim = Limiter(redis)
        held = await lim.reserve("u001", FREE, reservation_amount(chat), T0, 600)
        primed = await prime(provider, chat)
        outcome = StreamOutcome(request_id=request_id, message_id="m1", input_estimate=estimate_input_tokens(chat))
        meter = Meter(SessionLocal, TABLE, "u001", CHAT, T0)
        gen = metered_events(Connected(), primed, outcome, lim, held.reservation, meter)  # type: ignore[arg-type]
        names: list[str] = []
        at_usage = None
        try:
            async for ev in gen:
                names.append(ev.event)
                if ev.event == "usage":
                    at_usage = await scalar("SELECT count(*) FROM s13.usage_events WHERE request_id = :rid",
                                            rid=request_id)
                if cut_after is not None and len(names) == cut_after:
                    break  # 利用者がここで接続を切った
        finally:
            await gen.aclose()
    return names, at_usage


@dbcheck("V5 ストリームの記録：完了・途中失敗・切断が各1行。完了は usage を送る前に記録済み・Redis と同じ量")
async def _():
    await clear_redis()
    await clear_events()
    failing = FakeProvider([*fake_script(FAKE_TEXT)[:2], ProviderError("overloaded", provider="fake", status_code=529)])
    done, at_usage = await stream_once(fake_ok(), "req_v5_1_done")
    failed, _ = await stream_once(failing, "req_v5_2_fail")
    cut, _ = await stream_once(fake_ok(), "req_v5_3_cut", cut_after=3)
    got = [(rid, src, out, i, o, usd(c)) for rid, src, out, i, o, c in await rows(
        "SELECT request_id, usage_source, outcome, input_tokens, output_tokens, cost_usd "
        "FROM s13.usage_events ORDER BY request_id")]
    async with redis_client() as redis:
        redis_used = (await Limiter(redis).quota_state("u001", FREE, T0)).used
    async with SessionLocal() as s:
        db_used = await tokens_between(s, "u001", *day_range(date(2026, 10, 2)))
    eq(done, ["start", "delta", "delta", "delta", "delta", "usage", "done"], "完了のイベント")
    eq((failed, cut), (["start", "delta", "delta", "error"], ["start", "delta", "delta"]), "途中失敗と切断")
    eq(at_usage, 1, "usage を受け取った時点の行数")
    eq(got, [("req_v5_1_done", "upstream", "completed", 34, 20, "0.00026800"),
             ("req_v5_2_fail", "estimated", "failed", 34, 12, "0.00018800"),
             ("req_v5_3_cut", "estimated", "cancelled", 34, 12, "0.00018800")], "台帳")
    eq((redis_used, db_used), (146, 146), "Redis と台帳")
    return ("完了 upstream 34／20・0.00026800（usage の時点で記録済み）／途中の 529 は estimated 34／12・0.00018800／"
            "delta 2個で切断も estimated 34／12・0.00018800／Redis 146・台帳 146")


@dbcheck("V6 二重記録の防止：同じ request_id は、続けて書いても同時に書いても1行（ON CONFLICT DO NOTHING）")
async def _():
    await clear_events()
    one = rec("req_v6", "u002", T0, Usage(34, 20))
    first = await save_usage(SessionLocal, one, TABLE)
    again = await save_usage(SessionLocal, one, TABLE)
    race = replace(one, request_id="req_v6_race")
    raced = await asyncio.gather(save_usage(SessionLocal, race, TABLE), save_usage(SessionLocal, race, TABLE))
    eq((first, again), (True, False), "続けて2回")
    eq(sorted(raced), [False, True], "同時に2回")
    eq(await scalar("SELECT count(*) FROM s13.usage_events"), 2, "行数")
    return "続けて2回 → True・False／同時に2回 → 片方だけ True／台帳は2行（request_id ごとに1行）"


@dbcheck("V7 単価の改定と再計算：各行の時刻に効いていた単価で計算し直す（10月の行は変わらない）")
async def _():
    await clear_events()
    for r in (rec("req_v7_oct", "u002", T0, Usage(34, 20)),
              rec("req_v7_nov", "u002", datetime(2026, 11, 1, 9, 0, tzinfo=JST), Usage(34, 20))):
        await save_usage(SessionLocal, r, TABLE)  # 改定をまだ表に入れていなかった
    sql = "SELECT request_id, cost_usd, price_from FROM s13.usage_events ORDER BY request_id"
    before = [(rid, usd(c), str(pf)) for rid, c, pf in await rows(sql)]
    async with SessionLocal() as s:
        changed = await recompute_costs(s, TABLE.with_rows(REVISION))
        await s.commit()
    after = [(rid, usd(c), str(pf)) for rid, c, pf in await rows(sql)]
    eq(before, [("req_v7_nov", "0.00026800", "2026-10-02"), ("req_v7_oct", "0.00026800", "2026-10-02")], "改定前")
    eq(changed, 1, "変わった行数")
    eq(after, [("req_v7_nov", "0.00013400", "2026-11-01"), ("req_v7_oct", "0.00026800", "2026-10-02")], "再計算後")
    return "改定前はどちらも 0.00026800／再計算で変わったのは1行：11月の行は 0.00013400（11月1日の単価）・10月の行はそのまま"


@dbcheck("V8 集計：ユーザー別・JST の日別。単価の無い行は 0 円にせず unpriced で数える。used_today も台帳から")
async def _():
    await clear_redis()
    await clear_events()
    clock = FixedClock(datetime(2026, 10, 3, 18, 0, tzinfo=JST))
    seed = [rec("req_v8_0", "u001", datetime(2026, 10, 1, 12, 0, tzinfo=JST), Usage(34, 20)),  # 確認日より前
            rec("req_v8_1", "u001", datetime(2026, 10, 2, 23, 59, 59, tzinfo=JST), Usage(34, 20)),
            rec("req_v8_2", "u001", datetime(2026, 10, 3, 0, 0, tzinfo=JST), Usage(34, 20)),
            rec("req_v8_3", "u001", clock.now(), Usage(30, 181, 1084, 0)),
            rec("req_v8_4", "u002", datetime(2026, 10, 3, 12, 0, tzinfo=JST), Usage(34, 20))]
    for r in seed:
        await save_usage(SessionLocal, r, TABLE)
    unpriced_row = await rows("SELECT cost_usd, price_from FROM s13.usage_events WHERE request_id = 'req_v8_0'")
    async with SessionLocal() as s:
        days = await daily_usage(s, "u001", date(2026, 10, 1), date(2026, 10, 3))
    key = await issue("u001", clock)
    async with client_for(app, clock=clock, provider=fake_ok()) as (c, _):
        usage = (await c.get("/api/usage", headers=bearer(key))).json()
        daily = (await c.get("/api/usage/daily", params={"days": 3}, headers=bearer(key))).json()
    eq(unpriced_row, [(None, None)], "単価の無い行（cost_usd・price_from）")
    eq([(str(d.day), d.requests, d.input_tokens, d.output_tokens, d.cache_read_input_tokens, usd(d.cost_usd),
         d.unpriced) for d in days],
       [("2026-10-01", 1, 34, 20, 0, None, 1), ("2026-10-02", 1, 34, 20, 0, "0.00026800", 0),
        ("2026-10-03", 2, 64, 201, 1084, "0.00235480", 0)], "日別")
    eq(usage, {"plan": "free", "used_today": 1349, "limit_today": 20000, "requests_per_minute": 10}, "/api/usage")
    eq([(d["day"], d["requests"], d["cost_usd"], d["unpriced"]) for d in daily["days"]],
       [("2026-10-01", 1, None, 1), ("2026-10-02", 1, "0.00026800", 0), ("2026-10-03", 2, "0.00235480", 0)],
       "/api/usage/daily")
    return ("u001：10月1日 1件・金額 null・unpriced 1（確認日より前は単価なし。0 円にしない）／"
            "10月2日 1件・0.00026800（23:59:59）／10月3日 2件・入力64・出力201・読み出し1084・0.00235480"
            "（00:00:00 から）／u002 の行は入らない／used_today 1349")


@dbcheck("V9 Redis と台帳の食い違い：予約中の分と、消えた Redis。used_today は台帳（正）を返す")
async def _():
    await clear_redis()
    await clear_events()
    clock = FixedClock()
    key = await issue("u004", clock)
    async with client_for(app, clock=clock, provider=fake_ok()) as (c, redis):
        lim = Limiter(redis)

        async def both() -> tuple[int, int, int]:
            state = await lim.quota_state("u004", PRO, clock.now())
            used = (await c.get("/api/usage", headers=bearer(key))).json()["used_today"]
            return state.used, state.remaining, used

        await c.post("/api/ask", json=ASK, headers=bearer(key))
        after_ask = await both()
        await lim.reserve("u004", PRO, 1058, clock.now(), 600)  # 処理中の要求（まだ精算していない）
        holding = await both()
        await redis.delete(lim.quota_key("u004", clock.now()))  # Redis の再起動（この compose の Redis は永続化しない）
        lost = await both()
    eq(after_ask, (54, 199946, 54), "1回目のあと（Redis used・Redis 残り・台帳）")
    eq(holding, (54, 198888, 54), "予約中")
    eq(lost, (0, 200000, 54), "Redis が消えたあと")
    return ("1回目のあと Redis 54・台帳 54／予約中は Redis の残り 198888（予約 1058 を引く）・台帳 54／"
            "Redis が消えると Redis 0・台帳 54（/api/usage は 54 のまま）")


@dbcheck("V10 予算：今月の使用額＋この1回の見積もりが予算を超えるなら、上流を呼ぶ前に 402 budget_exceeded")
async def _():
    await clear_redis()
    await clear_events()
    clock = FixedClock()
    budget = BudgetSettings(users={"u003": Decimal("0.05"), "u005": Decimal("0.05")})
    morning = datetime(2026, 10, 2, 9, 0, tzinfo=JST)
    await save_usage(SessionLocal, rec("req_v10_u003", "u003", morning, Usage(0, 4000)), TABLE)  # 0.04 USD
    await save_usage(SessionLocal, rec("req_v10_u005", "u005", morning, Usage(0, 3000)), TABLE)  # 0.03 USD
    key3, key5 = await issue("u003", clock), await issue("u005", clock)
    fake = fake_ok()
    async with client_for(app, clock=clock, provider=fake, budget=budget) as (c, redis):
        over = await c.post("/api/ask", json=ASK, headers=bearer(key3))
        quota = await Limiter(redis).quota_state("u003", FREE, clock.now())
        ok = await c.post("/api/ask", json=ASK, headers=bearer(key5))
    november = FixedClock(datetime(2026, 11, 1, 0, 0, tzinfo=JST))
    async with client_for(app, clock=november, provider=fake, budget=budget) as (c, _):
        nov = await c.post("/api/ask", json=ASK, headers=bearer(key3))
    err = over.json()["error"]
    eq(usd(estimate_cost(chat_request(), TABLE.price_for(CHAT, T0))), "0.01030800", "1回の見積もり（34＋1024）")
    eq((over.status_code, err["type"], err["message"]), (402, "budget_exceeded", MESSAGES["budget_exceeded"]), "本文")
    eq((err["request_id"], "retry-after" in over.headers), (over.headers["x-request-id"], False), "ヘッダ")
    eq((quota.used, quota.reserved), (0, 0), "予約していない")
    eq((ok.status_code, nov.status_code, len(fake.requests)), (200, 200, 2), "u005・11月・上流に届いた数")
    eq(BudgetSettings().monthly_for("u001", "free"), Decimal("1.00"), "free の既定")
    return ("見積もり 0.01030800／u003（今月 0.04・予算 0.05）は 402 budget_exceeded・上流を呼ばず予約もしない／"
            "u005（今月 0.03）は 200／11月1日 0:00 の u003 は 200（月が替わると戻る）")


@dbcheck("V11 単価表に無いモデルは見積もれないので、上流を呼ばずに 500 internal_error（0 円で通さない）")
async def _():
    await clear_redis()
    await clear_events()
    clock = FixedClock()
    key = await issue("u001", clock)
    fake = fake_ok()
    async with client_for(app, clock=clock, provider=fake) as (c, _):
        app.dependency_overrides[get_model] = lambda: "unknown-model"
        r = await c.post("/api/ask", json=ASK, headers=bearer(key))
    err = r.json()["error"]
    eq((r.status_code, err["type"], err["message"]), (500, "internal_error", MESSAGES["internal_error"]), "応答")
    eq((len(fake.requests), await scalar("SELECT count(*) FROM s13.usage_events")), (0, 0), "上流と台帳")
    return "単価表に無いモデル → 500 internal_error・上流は呼ばない・台帳にも書かない"


finish("session13")
