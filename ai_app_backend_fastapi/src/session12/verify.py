"""Session 12（ジョブキュー）の検証。api コンテナの中で実行する（worker に実際にジョブを投げる）：

    docker compose restart worker          # tasks.py を読み込ませる（変更したら毎回）
    docker compose exec api python src/session12/verify.py
    docker compose exec api bash verify-all.sh src/session12   # 練習問題の検証も含めて実行

1日分の処理時間（work_seconds）を 0.05〜0.3 秒に縮めて、全体が十数秒で終わるようにしている。
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date

import httpx2
from redis.exceptions import ConnectionError as RedisConnectionError
from ulid import ULID

from kondate.clock import FixedClock
from kondate.data import load_recipes
from kondate.db import engine
from kondate.verifykit import check, eq, finish
from kondate.worker import app as celery_app

from src.session12.app import JobSettings, app, new_job
from src.session12.harness import (URL, bearer, clear_redis, client_for, dbcheck, issue, no_sleep, overrides,
                                   prepare_db, read_sse, redis_client, serve, submit, wait_job)
from src.session12.planner import UnknownUser, build_plan, find_user, plan_day
from src.session12.runner import TransientJobError, decide, execute, run_plan
from src.session12.store import ALREADY_RECORDED, JobStore
from src.session12.tasks import plan_week

CLOCK = FixedClock()  # 2026-10-02 18:00 JST → 献立の初日は 2026-10-03
START = date(2026, 10, 3)
FAST = JobSettings(work_seconds=0.05)
JOB_ID = re.compile(r"job_[0-9A-HJKMNP-TV-Z]{26}")  # job_ + ULID（Crockford の Base32・26文字）
RECIPES = {r["id"]: r for r in load_recipes()}


async def _setup() -> dict[str, str]:
    await prepare_db()
    await clear_redis()
    keys = {u: await issue(u, CLOCK) for u in ("u001", "u002", "u003")}
    await engine.dispose()
    return keys


KEYS = asyncio.run(_setup())


def allergens_of(days: list[dict]) -> set[str]:
    return {a for d in days for rid in d["recipe_ids"] for a in RECIPES[rid]["allergens"]}


@check("V1 worker が s12.plan_week を読み込んでいる（acks_late・reject_on_worker_lost）")
def _():
    replies = celery_app.control.inspect(timeout=3, limit=1).registered() or {}
    names = {n.split()[0] for tasks in replies.values() for n in tasks}
    assert "s12.plan_week" in names, "worker が s12.plan_week を知りません。docker compose restart worker を実行してください"
    eq((plan_week.acks_late, plan_week.reject_on_worker_lost, plan_week.ignore_result), (True, True, True),
       "タスクの設定")
    return "s12.plan_week（acks_late=True・reject_on_worker_lost=True・ignore_result=True）"


@dbcheck("V2 POST は処理を待たずに 202・job_id・Location を返す（入力の誤りは 422、認証なしは 401）")
async def _():
    async with client_for(app, clock=CLOCK, settings=FAST) as (client, _):
        r = await client.post(URL, json={"days": 7}, headers=bearer(KEYS["u002"]))
        eq(r.status_code, 202, "status")
        job_id = r.json()["job_id"]
        assert JOB_ID.fullmatch(job_id), job_id
        eq(r.json(), {"job_id": job_id, "status": "queued"}, "本文")
        eq(r.headers["location"], f"/api/jobs/{job_id}", "Location")
        eq(ULID.from_str(job_id[4:]).datetime, CLOCK.now(), "ID に入った時刻")
        bad = [await client.post(URL, json=b, headers=bearer(KEYS["u002"]))
               for b in ({"days": 0}, {"days": 15}, {"days": 7, "user_id": "u001"})]
        eq([x.status_code for x in bad], [422, 422, 422], "days の範囲外・user_id の指定")
        eq((await client.post(URL, json={"days": 7})).status_code, 401, "認証なし")
        await wait_job(client, job_id, KEYS["u002"])
    return "202・job_ + ULID（時刻は注入した時計）・Location /api/jobs/{job_id}・days 0/15 と user_id 付きは 422・認証なしは 401"


@dbcheck("V3 worker が7日分を作り、GET が succeeded と結果を返す（u002 はえび・かにを含まない）")
async def _():
    async with client_for(app, clock=CLOCK, settings=FAST) as (client, redis):
        job_id = await submit(client, KEYS["u002"])
        job = await wait_job(client, job_id, KEYS["u002"])
        ttls = [await redis.ttl(k) for k in JobStore(redis).keys(job_id)]
    eq((job["status"], job["done"], job["total"], job["error"]), ("succeeded", 7, 7, None), "状態")
    days = job["result"]["days"]
    eq([d["date"] for d in days], [f"2026-10-{n:02d}" for n in range(3, 10)], "日付")
    eq(allergens_of(days) & {"えび", "かに"}, set(), "アレルギーの原材料")
    eq(len({d["recipe_ids"][0] for d in days}), 7, "主菜が重ならない")
    eq(job["result"], build_plan(find_user("u002"), 7, START), "一度に作った結果（build_plan）")
    assert all(0 < t <= 3600 for t in ttls), ttls
    return "7日（2026-10-03〜2026-10-09）・主菜7種・えび/かに 0件・build_plan と一致・3つのキーとも保存期限 3600 秒以内"


@dbcheck("V4 SSE は progress 0..7 → done {result} を届ける（実行中・終了後・Last-Event-ID の続きから）")
async def _():
    async with overrides(app, clock=CLOCK, settings=JobSettings(work_seconds=0.2)), serve(app) as base:
        async with httpx2.AsyncClient(base_url=base, timeout=30) as client:
            headers = bearer(KEYS["u002"])
            job_id = await submit(client, KEYS["u002"])
            url = f"/api/jobs/{job_id}/events"
            live = await read_sse(client, url, headers)  # 登録の直後から購読する（実行中）
            replay = await read_sse(client, url, headers)  # 終わってから購読する
            rest = await read_sse(client, url, {**headers, "Last-Event-ID": live[3]["id"]})
            job = await wait_job(client, job_id, KEYS["u002"])
    eq([e["event"] for e in live], ["progress"] * 8 + ["done"], "イベントの並び")
    eq([e["data"] for e in live[:8]], [{"done": n, "total": 7} for n in range(8)], "progress の中身")
    eq(live[-1]["data"], {"result": job["result"]}, "done の中身＝GET の result")
    eq(replay, live, "終わってから購読しても同じ")
    eq([e["event"] for e in rest], ["progress"] * 4 + ["done"], "Last-Event-ID（progress 3）の続き")
    eq([e["data"]["done"] for e in rest[:4]], [4, 5, 6, 7], "続きの done")
    return "progress×8（done 0〜7・total 7）→ done・終わってから購読しても同じ・Last-Event-ID の続きは progress×4 → done"


@dbcheck("V5 他人のジョブは GET・SSE・DELETE とも 404、認証なしは 401")
async def _():
    async with client_for(app, clock=CLOCK, settings=FAST) as (client, _):
        job_id = await submit(client, KEYS["u002"])
        other = bearer(KEYS["u001"])
        rs = [await client.get(f"/api/jobs/{job_id}", headers=other),
              await client.get(f"/api/jobs/{job_id}/events", headers=other),
              await client.delete(f"/api/jobs/{job_id}", headers=other)]
        eq([r.status_code for r in rs], [404, 404, 404], "他人のジョブ")
        eq(rs[1].headers["content-type"].split(";")[0], "application/json", "SSE を始める前の 404 は JSON")
        eq({r.json()["error"]["type"] for r in rs}, {"not_found"}, "種別")
        missing = await client.get(f"/api/jobs/job_{ULID.from_datetime(CLOCK.now())}", headers=bearer(KEYS["u002"]))
        eq(missing.status_code, 404, "存在しないジョブ")
        r = await client.get(f"/api/jobs/{job_id}")
        eq((r.status_code, r.headers.get("www-authenticate")), (401, "Bearer"), "認証なし")
        job = await wait_job(client, job_id, KEYS["u002"])
    eq(job["status"], "succeeded", "他人の DELETE では止まらない")
    return "他人：GET/SSE/DELETE とも 404 not_found（SSE も JSON）・無い ID も 404・認証なしは 401・他人の DELETE では止まらない"


@dbcheck("V6 実行中のキャンセル：DELETE は 202、worker が日の区切りで中止フラグに気づいて cancelled")
async def _():
    async with client_for(app, clock=CLOCK, settings=JobSettings(work_seconds=0.3)) as (client, _):
        key = KEYS["u002"]
        job_id = await submit(client, key)
        await wait_job(client, job_id, key, until=lambda j: j["done"] >= 2)
        r = await client.delete(f"/api/jobs/{job_id}", headers=bearer(key))
        eq(r.status_code, 202, "実行中の DELETE")
        eq((r.json()["status"], r.json()["cancel_requested"]), ("running", True), "DELETE の直後")
        job = await wait_job(client, job_id, key)
        events = await read_sse(client, f"/api/jobs/{job_id}/events", bearer(key))
        again = await client.delete(f"/api/jobs/{job_id}", headers=bearer(key))
    eq((job["status"], job["result"]), ("cancelled", None), "止まったあと")
    assert 2 <= job["done"] < 7, job["done"]
    eq([e["event"] for e in events], ["progress"] * (job["done"] + 1) + ["cancelled"], "イベントの並び")
    eq(events[-1]["data"], {"done": job["done"], "total": 7}, "cancelled の中身")
    eq((again.status_code, again.json()["status"]), (200, "cancelled"), "2回目の DELETE")
    return "DELETE → 202（running・cancel_requested=true）→ cancelled・result なし・最後は cancelled {done, total}・2回目の DELETE は 200"


@dbcheck("V7 キュー待ちのキャンセル：その場で cancelled になり、配送の時刻が来ても走らない")
async def _():
    async with client_for(app, clock=CLOCK, settings=FAST) as (client, redis):
        store = JobStore(redis)
        job = new_job("u002", 7, CLOCK, FAST, "req_verify")
        await store.create(job, ttl=FAST.pending_ttl_seconds)
        # 1秒後に配送されるメッセージにして、確実に「キュー待ち」の間に DELETE する
        await asyncio.to_thread(plan_week.apply_async, args=[job.job_id], task_id=job.job_id, countdown=1)
        r = await client.delete(f"/api/jobs/{job.job_id}", headers=bearer(KEYS["u002"]))
        eq(r.status_code, 200, "キュー待ちの DELETE")
        eq((r.json()["status"], r.json()["done"]), ("cancelled", 0), "DELETE の直後")
        await asyncio.sleep(2.0)
        events = [e.event for e in await store.events(job.job_id)]
        after = await store.get(job.job_id)
    eq(events, ["cancelled"], "progress が1件も無い")
    eq((after.status, after.done), ("cancelled", 0), "配送の時刻の後")
    return "DELETE → 200 cancelled・2秒待っても progress 0件（revoke と状態の確認の二重で止める）"


@dbcheck("V8 同じジョブを何度実行しても、進捗と結果は重複しない（3日目で落ちた実行をやり直す）")
async def _():
    async with redis_client() as redis:
        store = JobStore(redis)
        job = new_job("u003", 7, CLOCK, FAST, "req_verify")
        await store.create(job, ttl=FAST.pending_ttl_seconds)
        user = find_user("u003")
        # 1回目の実行：3日分を記録したところで worker が落ちた（ack されないので再配送される）
        eq(await store.start(job.job_id), "running", "1回目の開始")
        for i in range(3):
            await store.advance(job.job_id, i, plan_day(user, i, START))
        # 2回目の実行（再配送）：記録済みの日は数えない
        eq(await store.advance(job.job_id, 1, plan_day(user, 1, START)), ALREADY_RECORDED, "記録済みの日")
        eq(await run_plan(store, job.job_id, sleep=no_sleep), "succeeded", "2回目の実行")
        events = await store.events(job.job_id)
        result = (await store.get(job.job_id)).result
        # 3回目の実行（成功のあとに、もう一度配送された）
        eq(await run_plan(store, job.job_id, sleep=no_sleep), "succeeded", "3回目の実行")
        eq(len(await store.events(job.job_id)), len(events), "3回目はイベントを足さない")
    eq([e.event for e in events], ["progress"] * 8 + ["done"], "イベントの並び")
    eq([json.loads(e.data)["done"] for e in events[:8]], list(range(8)), "done の重複なし")
    eq(result, build_plan(user, 7, START), "一度に作った結果と同じ")
    eq(allergens_of(result["days"]) & {"卵"}, set(), "u003 は卵を含まない")
    return "やり直しても progress×8（0〜7）→ done・結果は build_plan と同じ・3回目の実行は何もしない"


@dbcheck("V9 失敗の方針：一時的な失敗は待って再試行、上限か恒久的な失敗なら failed（固定文）")
async def _():
    waits_max = [decide(TransientJobError(), n, rand=lambda: 1.0).countdown for n in range(3)]
    waits_min = [decide(TransientJobError(), n, rand=lambda: 0.0).countdown for n in range(3)]
    eq((waits_max, waits_min), ([2.0, 4.0, 8.0], [1.0, 2.0, 4.0]), "再試行の待ち")
    eq(decide(TransientJobError(), 3).retry, False, "3回再試行したら終わり")
    eq([decide(e, 0).retry for e in (UnknownUser("u999"), ValueError("x"), RedisConnectionError(), TimeoutError())],
       [False, False, True, True], "失敗の種類")

    def flaky(user: dict, index: int, start: date) -> dict:
        if index == 4:
            raise TransientJobError("上流が一時的に使えない")
        return plan_day(user, index, start)

    async with redis_client() as redis:
        store = JobStore(redis)
        lost = new_job("u999", 7, CLOCK, FAST, "req_verify")  # 利用者がいない＝やり直しても直らない
        await store.create(lost, ttl=FAST.pending_ttl_seconds)
        eq(await execute(lost.job_id, retries=0, sleep=no_sleep), None, "恒久的な失敗は再試行しない")
        failed = await store.get(lost.job_id)
        failed_events = [e.event for e in await store.events(lost.job_id)]
        flaky_job = new_job("u001", 7, CLOCK, FAST, "req_verify")
        await store.create(flaky_job, ttl=FAST.pending_ttl_seconds)
        first = await execute(flaky_job.job_id, retries=0, sleep=no_sleep, day_planner=flaky, rand=lambda: 1.0)
        mid = await store.get(flaky_job.job_id)
        last = await execute(flaky_job.job_id, retries=3, sleep=no_sleep, day_planner=flaky)
        end = await store.get(flaky_job.job_id)
    eq(failed.status, "failed", "恒久的な失敗")
    eq(failed.error, {"type": "internal_error", "message": "サーバー内部でエラーが発生しました",
                      "request_id": "req_verify"}, "失敗の中身（例外の文は出さない）")
    eq(failed_events, ["progress", "error"], "イベント")
    eq((first, mid.status, mid.done), (2.0, "running", 4), "一時的な失敗：4日分を残して再試行を待つ")
    eq((last, end.status, end.done), (None, "failed", 4), "再試行の上限")
    return "再試行の待ち 2/4/8 秒（ジッタの下限 1/2/4 秒）・3回で打ち切り・未知の利用者は即 failed（internal_error）・一時的な失敗は記録を残して再試行"


@dbcheck("V10 保存期限：終わったジョブは result_ttl の後に消え、GET は 404 になる")
async def _():
    short = JobSettings(work_seconds=0.05, result_ttl_seconds=1)
    async with client_for(app, clock=CLOCK, settings=short) as (client, redis):
        job_id = await submit(client, KEYS["u002"])
        job = await wait_job(client, job_id, KEYS["u002"])
        await asyncio.sleep(1.5)
        r = await client.get(f"/api/jobs/{job_id}", headers=bearer(KEYS["u002"]))
        remaining = await redis.exists(*JobStore(redis).keys(job_id))
    eq(job["status"], "succeeded", "終了")
    eq((r.status_code, remaining), (404, 0), "保存期限の後")
    return "result_ttl=1 のジョブは 1.5 秒後に 404・3つのキーとも消える"


finish("session12")
