"""Session 10（レート制限とクォータ）の動作確認。api コンテナの中で実行する：

    docker compose exec api python src/session10/verify.py
    docker compose exec api bash verify-all.sh src/session10   # 練習問題の検証も含めて実行
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

from kondate.clock import JST, FixedClock
from kondate.db import engine
from kondate.verifykit import check, eq, finish, sse_events
from src.session10.app import app
from src.session10.bad import naive_take, utc_day
from src.session10.errors import MESSAGES
from src.session10.harness import (FAKE_TEXT, PROMPT, Connected, CountingProvider, bearer, clear_redis, client_for,
                                   dbcheck, issue, mock_provider, prepare_db, redis_client, settled_state)
from src.session10.limiter import Limiter, epoch_ms
from src.session10.plans import LimitSettings, PlanLimits, jst_day, seconds_until_reset
from src.session10.providers import ChatRequest, FakeProvider, ProviderError, Usage, fake_script
from src.session10.ratelimit import reservation_amount
from src.session10.relay import StreamOutcome, estimate_input_tokens, prime
from src.session10.stream import settled_events

FREE = PlanLimits(10, 20_000)
PRO = PlanLimits(60, 200_000)
ASK = {"message": PROMPT}


def fake_ok() -> FakeProvider:
    return FakeProvider(fake_script(FAKE_TEXT, usage=Usage(34, 20)))  # 1回 54 トークン


async def _setup() -> None:
    try:
        await prepare_db()
    finally:
        await engine.dispose()


asyncio.run(_setup())


@check("V1 トークンバケット（Lua）：free は続けて10回通り、11回目は 6000 ミリ秒待ち。6秒で1回ぶん戻る")
async def _():
    await clear_redis()
    clock = FixedClock()
    async with redis_client() as redis:
        lim = Limiter(redis)
        burst = [await lim.take_request("u001", FREE, clock.now()) for _ in range(11)]
        clock.advance(6)
        after6 = [await lim.take_request("u001", FREE, clock.now()) for _ in range(2)]
        clock.advance(60)
        after60 = await lim.take_request("u001", FREE, clock.now())
    eq([r.allowed for r in burst], [True] * 10 + [False], "続けて11回")
    eq([r.remaining for r in burst[:10]], list(range(9, -1, -1)), "残りの回数")
    eq(burst[10].retry_after_ms, 6000, "11回目の待ち")
    eq([(r.allowed, r.remaining, r.retry_after_ms) for r in after6], [(True, 0, 0), (False, 0, 6000)], "6秒後")
    eq((after60.allowed, after60.remaining), (True, 9), "さらに60秒後（満タンから1回）")
    return "10回通過（残り 9→0）・11回目は拒否で 6000ms・6秒後に1回だけ通過・60秒後は満タンに戻り残り 9"


@check("V2 原子性：Lua なら20並行でもちょうど10回。読む→書くの Bad は残り1回に2回とも通す")
async def _():
    await clear_redis()
    clock = FixedClock()
    async with redis_client() as redis:
        lim = Limiter(redis)
        results = await asyncio.gather(*[lim.take_request("u005", FREE, clock.now()) for _ in range(20)])
        key, now_ms = "s10:bad:u005", epoch_ms(clock.now())
        for _ in range(9):
            await naive_take(redis, key, FREE, now_ms)
        other: list[bool] = []

        async def another_server() -> None:
            other.append(await naive_take(redis, key, FREE, now_ms))

        first = await naive_take(redis, key, FREE, now_ms, between=another_server)
    eq(sum(r.allowed for r in results), 10, "Lua：20並行で通った数")
    eq((first, other), (True, [True]), "Bad：残り1回を2つの要求が同時に読んだ結果")
    return "Lua：20並行で通過 10・拒否 10／Bad：残り1回のところへ割り込まれ、2回とも通過（11回目が漏れる）"


@check("V3 プラン別の上限は設定で持ち、環境変数で上書きできる（pro は 61 回目が 1000 ミリ秒待ち）")
async def _():
    s = LimitSettings()
    eq((s.for_plan("free"), s.for_plan("pro")), (FREE, PRO), "既定")
    os.environ["LIMIT_FREE_REQUESTS_PER_MINUTE"] = "20"
    try:
        eq(LimitSettings().for_plan("free"), PlanLimits(20, 20_000), "環境変数で上書き")
    finally:
        del os.environ["LIMIT_FREE_REQUESTS_PER_MINUTE"]
    try:
        s.for_plan("team")
        raise AssertionError("未知のプランが通った")
    except ValueError:
        pass
    await clear_redis()
    clock = FixedClock()
    async with redis_client() as redis:
        lim = Limiter(redis)
        burst = [await lim.take_request("u002", PRO, clock.now()) for _ in range(61)]
    eq((sum(r.allowed for r in burst), burst[60].retry_after_ms), (60, 1000), "pro の61回")
    return "free 10回/分・20000トークン/日、pro 60回/分・200000トークン/日・LIMIT_FREE_REQUESTS_PER_MINUTE=20 で 20・pro は 61回目が 1000ms"


@check("V4 クォータの1日は JST で区切る（UTC の日付で切ると JST の 9:00 に戻ってしまう）")
def _():
    before = datetime(2026, 10, 2, 23, 59, 59, tzinfo=JST)
    after = before + timedelta(seconds=1)
    morning = datetime(2026, 10, 3, 8, 59, 59, tzinfo=JST)
    eq((jst_day(before), jst_day(after)), ("20261002", "20261003"), "JST の 0 時")
    eq((utc_day(morning), utc_day(morning + timedelta(seconds=1))), ("20261002", "20261003"), "UTC で切ると 9:00")
    eq((seconds_until_reset(FixedClock().now()), seconds_until_reset(before), seconds_until_reset(after)),
       (21600, 1, 86400), "0 時までの秒数")
    return "23:59:59 → 20261002・00:00:00 → 20261003（UTC で切ると 08:59:59 と 09:00:00 の間で変わる）・18:00 からの retry-after は 21600 秒"


@dbcheck("V5 HTTP：free の u001 は1分に10回まで。11回目は 429 rate_limited（retry-after: 6）")
async def _():
    await clear_redis()
    clock = FixedClock()
    key = await issue("u001", clock)
    fake = fake_ok()
    async with client_for(app, clock=clock, provider=fake) as (c, _):
        rs = [await c.post("/api/ask", json=ASK, headers=bearer(key)) for _ in range(11)]
    eq([r.status_code for r in rs], [200] * 10 + [429], "status")
    eq([r.headers["x-ratelimit-remaining-requests"] for r in rs[:10]], [str(i) for i in range(9, -1, -1)], "残り")
    eq((rs[0].json()["used_today"], rs[9].json()["used_today"], rs[9].headers["x-ratelimit-remaining-tokens"]),
       (54, 540, "19460"), "トークンの使用量")
    last = rs[10]
    err = last.json()["error"]
    eq((err["type"], err["message"], err["request_id"]), ("rate_limited", MESSAGES["rate_limited"],
                                                         last.headers["x-request-id"]), "本文")
    eq((last.headers["retry-after"], last.headers["x-ratelimit-limit-requests"],
        last.headers["x-ratelimit-remaining-requests"]), ("6", "10", "0"), "ヘッダ")
    eq(len(fake.requests), 10, "上流に届いた数")
    return ("200×10（残り 9→0・used_today 54→540）→ 429 rate_limited・retry-after: 6・"
            "x-ratelimit-remaining-requests: 0・上流に届いたのは10回")


@dbcheck("V6 クォータ：予約が1日の上限を超えると 429 quota_exceeded（retry-after は JST の 0 時まで）")
async def _():
    await clear_redis()
    clock = FixedClock()
    key3, key2 = await issue("u003", clock), await issue("u002", clock)
    async with client_for(app, clock=clock, provider=fake_ok()) as (c, redis):
        lim = Limiter(redis)
        seeded = await lim.reserve("u003", FREE, 19_000, clock.now(), 600)
        await lim.settle(seeded.reservation, 19_000)
        over = await c.post("/api/ask", json=ASK, headers=bearer(key3))
        pro = await c.post("/api/ask", json=ASK, headers=bearer(key2))
        clock.advance(21600)  # 2026-10-03 00:00 JST
        tomorrow = await c.post("/api/ask", json=ASK, headers=bearer(key3))
    err = over.json()["error"]
    eq((over.status_code, err["type"], err["message"]), (429, "quota_exceeded", MESSAGES["quota_exceeded"]), "本文")
    eq((over.headers["retry-after"], over.headers["x-ratelimit-limit-tokens"],
        over.headers["x-ratelimit-remaining-tokens"]), ("21600", "20000", "1000"), "ヘッダ")
    eq((pro.status_code, tomorrow.status_code, tomorrow.json()["used_today"]), (200, 200, 54), "pro と翌日")
    return ("u003（使用済み 19000）は予約 1058 が入らず 429 quota_exceeded・retry-after: 21600・残り 1000 トークン／"
            "u002（pro）は 200／翌日 00:00 JST に 200（used_today 54）")


@check("V7 予約と精算：max_tokens 分を仮押さえして実際の量で精算。二重の精算は無視、放置された予約は期限で消える")
async def _():
    await clear_redis()
    clock = FixedClock()
    chat = ChatRequest(messages=[{"role": "user", "content": PROMPT}], max_tokens=1024)
    async with redis_client() as redis:
        lim = Limiter(redis)
        amount = reservation_amount(chat)
        r1 = await lim.reserve("u001", FREE, amount, clock.now(), 600)
        held = await lim.quota_state("u001", FREE, clock.now())
        used = await lim.settle(r1.reservation, 54)
        again = await lim.settle(r1.reservation, 54)
        settled = await lim.quota_state("u001", FREE, clock.now())
        await lim.reserve("u001", FREE, amount, clock.now(), 600)  # 精算されない予約（落ちたプロセスの分）
        clock.advance(601)
        r3 = await lim.reserve("u001", FREE, amount, clock.now(), 600)
        fields = sorted(f.split(":")[0] for f in await redis.hkeys(r3.reservation.key))
    eq((estimate_input_tokens(chat), amount), (34, 1058), "予約量＝入力の見積もり＋max_tokens")
    eq((held.used, held.reserved, held.remaining), (0, 1058, 18942), "予約中")
    eq((used, again), (54, None), "精算と二重の精算")
    eq((settled.used, settled.reserved, settled.remaining), (54, 0, 19946), "精算後")
    eq((r3.state.used, r3.state.reserved, fields), (54, 1058, ["r", "used"]), "期限切れの予約を捨てたあと")
    return ("予約 1058（34＋1024）→ 使用 0・予約中 1058・残り 18942 → 精算 54 → 使用 54・残り 19946・"
            "2回目の精算は無視・600秒を過ぎた予約は次の予約のときに消える")


@dbcheck("V8 払い戻し：上流が失敗したら全額、ストリームを途中で切ったら送った分だけ精算する")
async def _():
    await clear_redis()
    clock = FixedClock()
    key = await issue("u004", clock)
    failing = FakeProvider([ProviderError("overloaded", provider="fake", status_code=529)])
    async with client_for(app, clock=clock, provider=failing) as (c, redis):
        failed = await c.post("/api/ask", json=ASK, headers=bearer(key))
        after_fail = await Limiter(redis).quota_state("u004", PRO, clock.now())

    async with redis_client() as redis:
        lim = Limiter(redis)
        chat = ChatRequest(messages=[{"role": "user", "content": PROMPT}], max_tokens=1024)
        held = await lim.reserve("u004", PRO, reservation_amount(chat), clock.now(), 600)
        primed = await prime(fake_ok(), chat)
        outcome = StreamOutcome(request_id="req_verify", message_id="m1", input_estimate=estimate_input_tokens(chat))
        gen = settled_events(Connected(), primed, outcome, lim, held.reservation)  # type: ignore[arg-type]
        got = [(await anext(gen)).event for _ in range(3)]
        await gen.aclose()  # 利用者が delta 2個で接続を切った
        after_cancel = await lim.quota_state("u004", PRO, clock.now())

    async with client_for(app, clock=clock, provider=fake_ok()) as (c, redis):
        r = await c.post("/api/chat/stream", json=ASK, headers=bearer(key))
        events = [e["event"] for e in sse_events(r.text.split("\n"))]
        after_done = await settled_state(Limiter(redis), "u004", PRO, clock)

    eq((failed.status_code, failed.json()["error"]["type"]), (503, "upstream_unavailable"), "上流の失敗")
    eq((after_fail.used, after_fail.reserved), (0, 0), "失敗のあと")
    eq((got, outcome.reason, outcome.usage_source, outcome.usage), (["start", "delta", "delta"], "cancelled",
                                                                    "estimated", Usage(34, 12)), "途中で切った")
    eq((after_cancel.used, after_cancel.reserved), (46, 0), "切ったあと")
    eq(events, ["start", "delta", "delta", "delta", "delta", "usage", "done"], "最後まで読んだストリーム")
    eq((after_done.used, after_done.reserved), (100, 0), "完了のあと")
    return ("上流 529 → 503 upstream_unavailable・使用 0（全額払い戻し）／delta 2個で切断 → 見積もり 34＋12 を精算し使用 46／"
            "最後まで → 54 を精算し使用 100・予約はどれも残らない")


@dbcheck("V9 上流の 429（mockllm）：retry-after を引き継いで全額払い戻し、待つ間は上流を呼ばない")
async def _():
    await clear_redis()
    clock = FixedClock()
    key = await issue("u002", clock)
    async with mock_provider({"x-mock-fault": "429", "x-mock-retry-after": "7"}) as p:
        counting = CountingProvider(p)
        async with client_for(app, clock=clock, provider=counting) as (c, redis):
            first = await c.post("/api/ask", json=ASK, headers=bearer(key))
            clock.advance(3)
            waiting = await c.post("/api/ask", json=ASK, headers=bearer(key))
            clock.advance(4)
            again = await c.post("/api/ask", json=ASK, headers=bearer(key))
            state = await Limiter(redis).quota_state("u002", PRO, clock.now())
    got = [(r.status_code, r.json()["error"]["type"], r.headers["retry-after"]) for r in (first, waiting, again)]
    eq(got, [(429, "rate_limited", "7"), (429, "rate_limited", "4"), (429, "rate_limited", "7")], "3回の応答")
    eq(counting.calls, 2, "上流を呼んだ回数")
    eq((state.used, state.reserved), (0, 0), "使用量と予約")
    assert "rate_limit_error" not in first.text, first.text
    return ("1回目 上流の 429 → retry-after: 7／3秒後 上流を呼ばずに retry-after: 4／7秒後 もう一度上流へ → 7・"
            "上流を呼んだのは2回・使用 0")


@dbcheck("V10 GET /api/usage：{plan, used_today, limit_today, requests_per_minute}（レート制限の回数は減らさない）")
async def _():
    await clear_redis()
    clock = FixedClock()
    key1, key2 = await issue("u001", clock), await issue("u002", clock)
    async with client_for(app, clock=clock, provider=fake_ok()) as (c, _):
        await c.post("/api/ask", json=ASK, headers=bearer(key1))
        views = [await c.get("/api/usage", headers=bearer(key1)) for _ in range(12)]
        pro = await c.get("/api/usage", headers=bearer(key2))
        nokey = await c.get("/api/usage")
        after = await c.post("/api/ask", json=ASK, headers=bearer(key1))
    eq([v.status_code for v in views], [200] * 12, "12回とも 200")
    eq(views[-1].json(), {"plan": "free", "used_today": 54, "limit_today": 20000, "requests_per_minute": 10}, "u001")
    eq(pro.json(), {"plan": "pro", "used_today": 0, "limit_today": 200000, "requests_per_minute": 60}, "u002")
    eq((nokey.status_code, nokey.json()["error"]["type"]), (401, "unauthorized"), "キーなし")
    eq(after.headers["x-ratelimit-remaining-requests"], "8", "usage を12回見たあとの残り")
    return ('u001 {"plan": "free", "used_today": 54, "limit_today": 20000, "requests_per_minute": 10}・'
            "12回見ても残りの回数は減らない（次の ask で 8）・u002 は pro・キーなしは 401")


finish("session10")
