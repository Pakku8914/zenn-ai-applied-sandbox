"""復習3（セッション2〜12の横断復習）の検証。api コンテナの中で実行する（worker は使わない）：

    docker compose exec api bash verify-all.sh src/review03

上流はすべて FakeProvider、時計は FixedClock、待ちは FakeSleep（実際には待たない）。
Celery の再試行は「execute_once が返した秒数だけ時計を進めて、retries を1つ増やしてもう一度呼ぶ」で再現する。
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta

from redis.exceptions import ConnectionError as RedisConnectionError

from kondate.clock import FixedClock
from kondate.db import engine
from kondate.verifykit import eq, finish

from src.review03.app import JobSettings, app, get_enqueue, new_job
from src.review03.harness import (URL, bearer, clear_redis, client_for, dbcheck, issue, make_llm, prepare_db,
                                  read_sse, redis_client, revoke, rotate)
from src.review03.idempotency import IdempotencyStore, fingerprint
from src.review03.limiter import Limiter, QuotaState
from src.review03.metered import QuotaExceeded, metered_complete
from src.review03.planner import UnknownUser, find_user, plan_day
from src.review03.plans import LimitSettings
from src.review03.providers import ChatRequest, FakeProvider, ProviderError, Usage, fake_script
from src.review03.ratelimit import reservation_amount, usage_tokens
from src.review03.runner import day_chat, decide, execute_once, job_error
from src.review03.store import JobStore

START = date(2026, 10, 3)  # FixedClock（2026-10-02 18:00 JST）の翌日
JOB_SETTINGS = JobSettings()
OK = fake_script("今日のひとことです。", usage=Usage(200, 100))  # 1日分 300 トークン
OK_LIGHT = fake_script("軽いモデルのひとことです。", usage=Usage(120, 80))  # 200 トークン
QUOTA_TEXT = "本日の利用上限に達しました。日付が変わってから再度お試しください。"


def e429() -> list[ProviderError]:
    return [ProviderError("rate_limited", provider="fake", status_code=429, retry_after=30)]


def e529() -> list[ProviderError]:
    return [ProviderError("overloaded", provider="fake", status_code=529)]


def one() -> float:
    return 1.0


def worker_deps(llm, limiter, clock, limit_settings: LimitSettings | None = None) -> dict:
    return {"llm": llm, "limiter": limiter, "limit_settings": limit_settings or LimitSettings(),
            "clock": clock, "rand": one}


async def make_job(store: JobStore, user_id: str, days: int, clock: FixedClock) -> str:
    job = new_job(user_id, days, clock, JOB_SETTINGS, "req_verify")
    await store.create(job, ttl=JOB_SETTINGS.pending_ttl_seconds)
    return job.job_id


async def quota(limiter: Limiter, user_id: str, clock: FixedClock,
                settings: LimitSettings | None = None) -> QuotaState:
    limits = (settings or LimitSettings()).for_plan(find_user(user_id)["plan"])
    return await limiter.quota_state(user_id, limits, clock.now())


def events_of(evs) -> list[tuple[str, dict]]:
    return [(e.event, json.loads(e.data)) for e in evs]


async def _setup() -> None:
    try:
        await prepare_db()
    finally:
        await engine.dispose()


asyncio.run(_setup())


async def bad_run(store: JobStore, job_id: str, llm, limiter: Limiter, clock: FixedClock) -> None:
    """問題1の後輩の runner：記録を上書きし、done を足し続け、失敗しても予約を返さない。"""
    job = await store.get(job_id)
    await store.start(job_id)
    user = find_user(job.user_id)
    limits = LimitSettings().for_plan(user["plan"])
    job_key, days_key, events_key = store.keys(job_id)
    for i in range(job.total):
        day = plan_day(user, i, date.fromisoformat(job.start_date))
        chat = day_chat(day)
        reserved = await limiter.reserve(job.user_id, limits, reservation_amount(chat), clock.now(), 600)
        served = await llm.complete(chat)
        await limiter.settle(reserved.reservation, usage_tokens(served.value.usage))
        await store.redis.hset(days_key, str(i), json.dumps(day, ensure_ascii=False))
        done = await store.redis.hincrby(job_key, "done", 1)
        await store.redis.xadd(events_key, {"event": "progress",
                                            "data": json.dumps({"done": done, "total": job.total})})
    days = await store.recorded_days(job_id)
    result = {"days": [days[i] for i in range(job.total)]}
    await store.finish(job_id, "succeeded", json.dumps(result, ensure_ascii=False), job.result_ttl)


@dbcheck("R1 問題1：429 の後の再試行で献立が二重にできる runner と、記録・払い戻し・待ち時間で止めた runner")
async def _():
    amount_day2 = reservation_amount(day_chat(plan_day(find_user("u001"), 2, START)))
    async with redis_client() as redis:
        store, limiter = JobStore(redis), Limiter(redis)
        # Bad：後輩の runner。再試行は失敗の種類にかかわらず2秒後
        await clear_redis()
        clock = FixedClock()
        primary, light = FakeProvider(OK, OK, e429(), OK), FakeProvider(e429())
        llm, _ = make_llm(redis, clock, primary, light)
        job_id = await make_job(store, "u001", 4, clock)
        try:
            await bad_run(store, job_id, llm, limiter, clock)
            raise AssertionError("1回目の実行は3日目で失敗するはず")
        except ProviderError as e:
            eq(e.kind, "rate_limited", "1回目の失敗")
        clock.advance(2)
        await bad_run(store, job_id, llm, limiter, clock)
        bad_job = await store.get(job_id)
        bad_events = events_of(await store.events(job_id))
        bad_quota = await quota(limiter, "u001", clock)
        bad_wait = await limiter.upstream_wait_ms(clock.now())
        bad_calls = (len(primary.requests), len(light.requests))
        # Good：runner.execute_once。再試行の待ちは返った秒数
        await clear_redis()
        clock = FixedClock()
        primary, light = FakeProvider(OK, OK, e429(), OK), FakeProvider(e429())
        llm, _ = make_llm(redis, clock, primary, light)
        job_id = await make_job(store, "u001", 4, clock)
        first = await execute_once(store, job_id, retries=0, **worker_deps(llm, limiter, clock))
        clock.advance(first)
        second = await execute_once(store, job_id, retries=1, **worker_deps(llm, limiter, clock))
        good_job = await store.get(job_id)
        good_events = events_of(await store.events(job_id))
        good_quota = await quota(limiter, "u001", clock)
        good_calls = (len(primary.requests), len(light.requests))
    eq((bad_job.status, bad_job.done, bad_job.total), ("succeeded", 6, 4), "Bad：done と total")
    eq([e for e, _ in bad_events], ["progress"] * 7 + ["done"], "Bad：イベントの並び")
    eq(bad_events[6][1], {"done": 6, "total": 4}, "Bad：最後の progress")
    eq(bad_calls, (7, 1), "Bad：上流の呼び出し（primary・light）")
    eq((bad_quota.used, bad_quota.reserved, bad_wait), (1800, amount_day2, 0), "Bad：使用量・残った予約・待ち時間")
    eq((first, second), (30.0, None), "Good：再試行までの秒")
    eq((good_job.status, good_job.done, good_job.total), ("succeeded", 4, 4), "Good：done と total")
    eq([e for e, _ in good_events], ["progress"] * 5 + ["done"], "Good：イベントの並び")
    eq([d["done"] for _, d in good_events[:5]], [0, 1, 2, 3, 4], "Good：progress の done")
    eq(good_calls, (5, 1), "Good：上流の呼び出し（primary・light）")
    eq((good_quota.used, good_quota.reserved), (1200, 0), "Good：使用量・残った予約")
    eq([d["recipe_ids"] for d in good_job.result["days"]],
       [plan_day(find_user("u001"), i, START)["recipe_ids"] for i in range(4)], "Good：献立")
    return ("Bad：done 6 / total 4・progress×7（最後は done 6）・上流 primary 7 回・light 1 回・used_today 1800・"
            "3日目の予約が残る・待ち時間の共有なし／Good：30 秒後に再試行・done 4 / total 4・progress×5 → done・"
            "上流 primary 5 回・light 1 回・used_today 1200・予約の残り 0")


@dbcheck("R2 問題2：ジョブの持ち主は利用者。失効したキーでは見られず、同じ利用者の別のキーなら見られる")
async def _():
    await clear_redis()
    clock = FixedClock()
    a, b, c = await issue("u001", clock), await issue("u001", clock), await issue("u003", clock)
    enqueued: list[str] = []
    async with client_for(app, clock=clock, enqueued=enqueued) as (client, redis):
        r = await client.post(URL, json={"days": 2}, headers=bearer(a.key))
        eq(r.status_code, 202, "キー A で登録")
        job_id = r.json()["job_id"]
        await revoke("u001", a.id, clock)  # 登録の直後に、キー A を失効させた
        llm, _ = make_llm(redis, clock, FakeProvider(OK), FakeProvider(OK_LIGHT))
        ran = await execute_once(JobStore(redis), job_id, retries=0, **worker_deps(llm, Limiter(redis), clock))
        url = f"/api/jobs/{job_id}/events"
        by_a = await client.get(url, headers=bearer(a.key))
        events = await read_sse(client, url, bearer(b.key))
        by_c = await client.get(url, headers=bearer(c.key))
        anon = await client.get(url)
        rest = await read_sse(client, url, {**bearer(b.key), "Last-Event-ID": events[1]["id"]})
        job = (await client.get(f"/api/jobs/{job_id}", headers=bearer(b.key))).json()
        b2 = await rotate("u001", b.id, clock, timedelta(hours=1))
        in_grace = (await client.get(f"/api/jobs/{job_id}", headers=bearer(b.key))).status_code
        clock.advance(3600)
        after_grace = (await client.get(f"/api/jobs/{job_id}", headers=bearer(b.key))).status_code
        new_key = (await client.get(f"/api/jobs/{job_id}", headers=bearer(b2.key))).status_code
    err = by_a.json()["error"]
    eq((ran, enqueued), (None, [job_id]), "ジョブの実行")
    eq((by_a.status_code, by_a.headers.get("www-authenticate"), err["type"], err["message"]),
       (401, "Bearer", "unauthorized", "認証が必要です"), "失効したキー A")
    eq([e["event"] for e in events], ["progress"] * 3 + ["done"], "別のキー B")
    eq([e["data"] for e in events[:3]], [{"done": n, "total": 2} for n in range(3)], "progress の中身")
    eq((by_c.status_code, by_c.headers["content-type"].split(";")[0], by_c.json()["error"]["type"]),
       (404, "application/json", "not_found"), "他人のキー C")
    eq((anon.status_code, anon.headers.get("www-authenticate")), (401, "Bearer"), "キーなし")
    eq([e["event"] for e in rest], ["progress", "done"], "Last-Event-ID の続き")
    eq(rest[0]["data"], {"done": 2, "total": 2}, "続きの progress")
    eq(job["status"], "succeeded", "キーを失効させてもジョブは止まらない")
    eq((in_grace, after_grace, new_key), (200, 401, 200), "ローテーション")
    return ("失効したキー A → 401（WWW-Authenticate: Bearer）・同じ利用者のキー B → 200（progress×3 → done）・"
            "他人のキー → 404（JSON）・キーなし → 401・Last-Event-ID（2件目）→ progress → done・"
            "ジョブは succeeded・ローテーションの旧キーは猶予内 200 → 猶予後 401・新キー 200")


@dbcheck("R3 問題3：フォールバックしても予約と精算は1回、引くのは利用者のプランのクォータ")
async def _():
    limits = LimitSettings().for_plan(find_user("u001")["plan"])
    chat = ChatRequest(messages=[{"role": "user", "content": "今夜の献立を1品提案してください。"}], max_tokens=300)
    async with redis_client() as redis:
        limiter = Limiter(redis)
        # 台本1：primary は毎回 529、light が答える
        await clear_redis()
        clock = FixedClock()
        llm, sleep = make_llm(redis, clock, FakeProvider(e529()), FakeProvider(OK_LIGHT))
        m = await metered_complete(llm, limiter, "u001", limits, chat, clock=clock, hold_seconds=600)
        state = await limiter.quota_state("u001", limits, clock.now())
        breaker = await redis.hmget("review03:cb:primary", ["state", "failures"])
        # 台本2：primary も light も 429（retry-after: 30）。primary は2回目から答える
        await clear_redis()
        clock = FixedClock()
        primary, light = FakeProvider(e429(), OK), FakeProvider(e429())
        llm2, _ = make_llm(redis, clock, primary, light)
        try:
            await metered_complete(llm2, limiter, "u001", limits, chat, clock=clock, hold_seconds=600)
            raise AssertionError("全経路が 429 なら失敗するはず")
        except ProviderError as e:
            first_error = (e.kind, e.retry_after)
        after_fail = await limiter.quota_state("u001", limits, clock.now())
        wait_ms = await limiter.upstream_wait_ms(clock.now())
        try:
            await metered_complete(llm2, limiter, "u001", limits, chat, clock=clock, hold_seconds=600)
            raise AssertionError("待ち時間の間は断るはず")
        except ProviderError as e:
            cooled = (e.kind, e.provider, e.retry_after)
        calls_while_cooling = (len(primary.requests), len(light.requests))
        clock.advance(30)
        recovered = await metered_complete(llm2, limiter, "u001", limits, chat, clock=clock, hold_seconds=600)
        final = await limiter.quota_state("u001", limits, clock.now())
    eq((m.served.route, m.served.fallback, m.served.reason), ("light", "light", "overloaded"), "台本1：答えた経路")
    eq([(a.route, a.number, a.outcome, a.waited) for a in m.served.attempts],
       [("primary", 1, "overloaded", 0.0), ("primary", 2, "overloaded", 0.5), ("light", 1, "ok", 0.0)], "試行の記録")
    eq(sleep.calls, [0.5], "待った秒")
    eq((m.reserved, m.charged, m.used_today), (reservation_amount(chat), 200, 200), "予約・精算・used_today")
    eq((state.used, state.reserved), (200, 0), "台本1：クォータ")
    eq(breaker, ["closed", "2"], "primary のブレーカ")
    eq(first_error, ("rate_limited", 30), "台本2：1回目の失敗")
    eq((after_fail.used, after_fail.reserved, wait_ms), (0, 0, 30_000), "払い戻しと待ち時間の共有")
    eq((cooled, calls_while_cooling), (("rate_limited", "limiter", 30), (1, 1)), "待ち時間の間は上流を呼ばない")
    eq((recovered.served.route, recovered.served.fallback, recovered.charged, final.used),
       ("primary", None, 300, 300), "30 秒後")
    return ("light で答えた（primary は overloaded×2・待ち 0.5 秒）・精算は1回で 200（light の 120 + 80）・"
            "used_today 200・予約の残り 0・primary の連続失敗 2（closed）／全経路 429 → 払い戻して used 0・"
            "待ち時間 30 秒を共有し、その間は上流を呼ばずに rate_limited・30 秒後は primary で 300")


@dbcheck("R4 問題4：登録は冪等キーで1回だけ。失敗とレート制限の 429 は記録せず、同じキーでやり直せる")
async def _():
    await clear_redis()
    clock = FixedClock()
    k1, k3 = await issue("u001", clock), await issue("u003", clock)
    enqueued: list[str] = []
    async with client_for(app, clock=clock, enqueued=enqueued) as (client, redis):
        def post(key: str, idem: str, days: int = 3):
            return client.post(URL, json={"days": days}, headers={**bearer(key), "Idempotency-Key": idem})

        first = await post(k1.key, "plan-1003")
        again = await post(k1.key, "plan-1003")
        changed = await post(k1.key, "plan-1003", days=4)
        other = await post(k3.key, "plan-1003")
        await IdempotencyStore(redis).begin("u001", "plan-busy", fingerprint("POST", URL, {"days": 3}))
        busy = await post(k1.key, "plan-busy")
        bad_key = await post(k1.key, "has space")
        before = [k async for k in redis.scan_iter("review03:job:*")]

        async def broken(job_id: str) -> None:
            raise RuntimeError("ブローカーに届かない")

        app.dependency_overrides[get_enqueue] = lambda: broken
        failed = await post(k1.key, "plan-fail")
        failed_left = await redis.exists("review03:idem:u001:plan-fail")
        after = [k async for k in redis.scan_iter("review03:job:*")]

        async def record(job_id: str) -> None:
            enqueued.append(job_id)

        app.dependency_overrides[get_enqueue] = lambda: record
        retried = await post(k1.key, "plan-fail")
    job1 = first.json()["job_id"]
    eq((first.status_code, first.headers["location"], first.headers.get("idempotent-replayed")),
       (202, f"/api/jobs/{job1}", None), "1回目")
    eq((again.status_code, again.json(), again.headers.get("idempotent-replayed"), again.headers["location"]),
       (202, first.json(), "true", f"/api/jobs/{job1}"), "同じキー・同じ本文")
    eq((changed.status_code, changed.json()["error"]["type"], changed.json()["error"]["message"]),
       (409, "idempotency_conflict", "この Idempotency-Key は、内容の異なる要求ですでに使われています。"), "本文違い")
    assert other.status_code == 202 and other.json()["job_id"] != job1, other.text
    eq((busy.status_code, busy.json()["error"]["message"], busy.headers.get("retry-after")),
       (409, "この Idempotency-Key の要求はまだ処理中です。しばらく待ってから再度お試しください。", "1"), "処理中")
    eq((bad_key.status_code, bad_key.json()["error"]["type"]), (422, "invalid_request"), "形の悪いキー")
    eq((failed.status_code, failed.json()["error"]["type"], failed.json()["error"]["message"]),
       (500, "internal_error", "サーバー内部でエラーが発生しました"), "積めなかった")
    eq((failed_left, len(after)), (0, len(before)), "積めなかったときに残るもの")
    eq((retried.status_code, retried.headers.get("idempotent-replayed")), (202, None), "同じキーでやり直す")
    eq(enqueued, [job1, other.json()["job_id"], retried.json()["job_id"]], "積んだジョブ")

    clock5 = FixedClock()
    k5 = await issue("u005", clock5)
    async with client_for(app, clock=clock5, enqueued=[],
                          limit_settings=LimitSettings(free_requests_per_minute=2)) as (client, redis):
        def post5(idem: str):
            return client.post(URL, json={"days": 3}, headers={**bearer(k5.key), "Idempotency-Key": idem})

        a1 = await post5("a")
        a2 = await post5("a")
        limited = await post5("b")
        b_left = await redis.exists("review03:idem:u005:b")
        clock5.advance(30)
        b1 = await post5("b")
    eq((a1.status_code, a2.status_code, a2.headers.get("idempotent-replayed")), (202, 202, "true"), "上限2回の利用者")
    eq((limited.status_code, limited.json()["error"]["type"], limited.headers.get("retry-after"),
        limited.headers.get("x-ratelimit-remaining-requests")), (429, "rate_limited", "30", "0"), "3回目")
    eq((b_left, b1.status_code, b1.headers.get("idempotent-replayed")), (0, 202, None), "429 の後に同じキー")
    return ("1回目 202・同じキーと本文 → 同じ job_id（idempotent-replayed: true）・本文違い → 409・"
            "別の利用者の同じキー → 別のジョブ・処理中 → 409（retry-after: 1）・形の悪いキー → 422・"
            "積めなかった → 500 で記録もジョブも残さない・積んだのは 3 件／再生も回数に数え、"
            "レート制限の 429（retry-after: 30）では冪等キーを記録しない")


@dbcheck("R5 問題5：失敗を分けて再試行し、クォータ切れは止め、フォールバックは記録に残す")
async def _():
    waits = [decide(ProviderError("rate_limited", provider="fake", retry_after=30), 0, rand=one).countdown,
             decide(ProviderError("overloaded", provider="fake"), 1, rand=one).countdown,
             decide(ProviderError("breaker_open", provider="fake"), 0, rand=lambda: 0.0).countdown,
             decide(ProviderError("rate_limited", provider="fake", retry_after=600), 0, rand=one).countdown,
             decide(RedisConnectionError(), 2, rand=one).countdown]
    eq(waits, [30.0, 4.0, 1.0, 60.0, 8.0], "再試行までの秒")
    quota_error = QuotaExceeded(QuotaState(20_000, 0, 20_000), 21_600)
    stops = [decide(e, n, rand=one).retry for e, n in ((ProviderError("overloaded", provider="fake"), 3),
                                                       (ProviderError("bad_request", provider="fake"), 0),
                                                       (quota_error, 0), (UnknownUser("u999"), 0))]
    eq(stops, [False, False, False, False], "再試行しない失敗")
    types = [job_error(e, "req_verify")["type"] for e in (
        quota_error, ProviderError("timeout", provider="fake"), ProviderError("rate_limited", provider="fake"),
        ProviderError("bad_request", provider="fake"), ProviderError("breaker_open", provider="fake"),
        UnknownUser("u999"))]
    eq(types, ["quota_exceeded", "upstream_timeout", "rate_limited", "upstream_error", "upstream_unavailable",
               "internal_error"], "失敗の種別")

    small = LimitSettings(free_tokens_per_day=800)
    amounts = [reservation_amount(day_chat(plan_day(find_user("u001"), i, START))) for i in range(4)]
    assert all(200 < a <= 500 for a in amounts), amounts  # 2日分は入り、3日目は入らない大きさ
    async with redis_client() as redis:
        store, limiter = JobStore(redis), Limiter(redis)
        await clear_redis()
        clock = FixedClock()
        primary = FakeProvider(OK)
        llm, _ = make_llm(redis, clock, primary, FakeProvider(OK_LIGHT))
        job_id = await make_job(store, "u001", 4, clock)
        ran = await execute_once(store, job_id, retries=0, **worker_deps(llm, limiter, clock, small))
        failed = await store.get(job_id)
        failed_events = [e.event for e in await store.events(job_id)]
        q = await quota(limiter, "u001", clock, small)
        calls = len(primary.requests)

        await clear_redis()
        clock = FixedClock()
        llm, sleep = make_llm(redis, clock, FakeProvider(e529()), FakeProvider(OK_LIGHT))
        job2 = await make_job(store, "u002", 1, clock)
        ran2 = await execute_once(store, job2, retries=0, **worker_deps(llm, limiter, clock))
        done2 = await store.get(job2)
        q2 = await quota(limiter, "u002", clock)
    eq((ran, failed.status, failed.done), (None, "failed", 2), "クォータ 800：再試行せず failed")
    eq(failed.error, {"type": "quota_exceeded", "message": QUOTA_TEXT, "request_id": "req_verify"}, "失敗の本文")
    eq(failed_events, ["progress"] * 3 + ["error"], "クォータ 800：イベント")
    eq((q.used, q.reserved, calls), (600, 0, 2), "クォータ 800：使用量・予約・上流の呼び出し")
    eq((ran2, done2.status), (None, "succeeded"), "primary が 529 の日")
    eq(done2.result["days"][0], {**plan_day(find_user("u002"), 0, START), "note": "軽いモデルのひとことです。",
                                 "fallback": "light"}, "記録した1日分")
    eq((q2.used, sleep.calls), (200, [0.5]), "pro の使用量と待ち")
    return ("再試行の待ち 30/4/1/60/8 秒・上限到達・上流の 400・クォータ切れ・未知の利用者は再試行しない・"
            "種別は quota_exceeded/upstream_timeout/rate_limited/upstream_error/upstream_unavailable/"
            "internal_error／クォータ 800 は2日分で failed（quota_exceeded・progress×3 → error・used 600・"
            "上流 2 回）／primary が 529 の日は light の答えを fallback: light で記録（used 200）")


@dbcheck("R6 問題6：冪等な登録 → 429 を挟んだ再試行 → フォールバック → 進捗と使用量まで通しで1回分だけ")
async def _():
    await clear_redis()
    clock = FixedClock()
    k = await issue("u001", clock)
    enqueued: list[str] = []
    async with client_for(app, clock=clock, enqueued=enqueued) as (client, redis):
        headers = {**bearer(k.key), "Idempotency-Key": "week-1003"}
        first = await client.post(URL, json={"days": 4}, headers=headers)
        again = await client.post(URL, json={"days": 4}, headers=headers)
        job_id = first.json()["job_id"]
        store, limiter = JobStore(redis), Limiter(redis)
        primary = FakeProvider(OK, OK, e429(), OK, e529())
        light = FakeProvider(e429(), OK_LIGHT)
        llm, sleep = make_llm(redis, clock, primary, light)
        c1 = await execute_once(store, job_id, retries=0, **worker_deps(llm, limiter, clock))
        clock.advance(2)  # 予定より早く配送された（待ち時間の共有で止まるか）
        c2 = await execute_once(store, job_id, retries=1, **worker_deps(llm, limiter, clock))
        calls_early = (len(primary.requests), len(light.requests))
        clock.advance(c2)
        c3 = await execute_once(store, job_id, retries=2, **worker_deps(llm, limiter, clock))
        job = (await client.get(f"/api/jobs/{job_id}", headers=bearer(k.key))).json()
        usage = (await client.get("/api/usage", headers=bearer(k.key))).json()
        events = await read_sse(client, f"/api/jobs/{job_id}/events", bearer(k.key))
        late = await client.post(URL, json={"days": 4}, headers=headers)
    eq((first.status_code, again.json()["job_id"], again.headers.get("idempotent-replayed"), enqueued),
       (202, job_id, "true", [job_id]), "2回の POST でジョブは1つ")
    eq((c1, c2, c3), (30.0, 28.0, None), "再試行までの秒")
    eq(calls_early, (3, 1), "早すぎた配送では上流を呼ばない")
    eq((job["status"], job["done"], job["total"]), ("succeeded", 4, 4), "ジョブの結末")
    eq([d["fallback"] for d in job["result"]["days"]], [None, None, None, "light"], "フォールバックの記録")
    eq((len(primary.requests), len(light.requests), sleep.calls), (6, 2, [0.5]), "上流の呼び出しと待ち")
    eq(usage, {"plan": "free", "used_today": 1100, "limit_today": 20_000, "requests_per_minute": 10}, "GET /api/usage")
    eq([e["event"] for e in events], ["progress"] * 5 + ["done"], "SSE")
    eq([e["data"]["done"] for e in events[:5]], [0, 1, 2, 3, 4], "progress の done")
    eq(events[-1]["data"], {"result": job["result"]}, "done の中身＝GET の result")
    eq((late.status_code, late.json(), late.headers.get("idempotent-replayed"), len(enqueued)),
       (202, {"job_id": job_id, "status": "queued"}, "true", 1), "終わった後の再生")
    return ("POST 2回でジョブ 1 件・3日目の 429 で 30 秒後に再試行・2 秒後の配送は上流を呼ばず 28 秒後へ・"
            "3回目で succeeded（done 4 / total 4）・上流 primary 6 回・light 2 回・4日目だけ fallback light・"
            "used_today 1100（300×3 + 200）・SSE は progress×5 → done・終わった後の再生は queued のまま")


finish("review03")
