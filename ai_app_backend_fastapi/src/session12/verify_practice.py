"""Session 12 の練習問題の解答を検証する（api コンテナの中で実行する）：

    docker compose exec api python src/session12/verify_practice.py
"""

from __future__ import annotations

import asyncio
import time

import httpx2

from kondate.clock import FixedClock
from kondate.db import engine
from kondate.verifykit import check, eq, finish
from kondate.worker import app as celery_app
from src.session12.app import JobSettings, app, new_job
from src.session12.errors import MESSAGES, ApiError
from src.session12.harness import (bearer, clear_redis, dbcheck, issue, overrides, prepare_db, redis_client, serve,
                                   submit)
from src.session12.keys import CurrentUser
from src.session12.q1_job_ids import job_created_at, parse_job_id
from src.session12.q2_visibility import ensure_visibility, visibility_timeout_of, worst_message_seconds
from src.session12.q3_follow import follow_job
from src.session12.q4_responsive import run_responsive
from src.session12.q5_policy import UpstreamRateLimited, decide_with_retry_after, result_ttl_for
from src.session12.q6_concurrency import ActiveJobs, admit
from src.session12.runner import TransientJobError
from src.session12.store import JobStore

CLOCK = FixedClock()
FAST = JobSettings(work_seconds=0.05)


async def _setup() -> str:
    await prepare_db()
    await clear_redis()
    key = await issue("u002", CLOCK)
    await engine.dispose()
    return key


KEY = asyncio.run(_setup())


@check("P1 ジョブ ID の形を確かめ、ID から登録時刻を読む")
def _():
    job_id = new_job("u002", 7, CLOCK, FAST, "req_verify").job_id
    eq(parse_job_id(job_id), job_id, "正しい ID")
    eq(parse_job_id("job_" + job_id[4:].lower()), job_id, "小文字は大文字に揃える")
    bad = ["job_ABC", "JOB_" + job_id[4:], "job_8" + job_id[5:], "job_" + job_id[4:-1] + "I", "job_../../etc",
           job_id[4:]]
    eq([parse_job_id(b) for b in bad], [None] * 6, "形の違う ID")
    eq(job_created_at(job_id).isoformat(), "2026-10-02T18:00:00+09:00", "登録時刻")
    return "正しい ID・小文字はそのまま通す（大文字に揃える）・形の違う6種は None・登録時刻 2026-10-02T18:00:00+09:00"


@check("P2 可視性タイムアウトの予算を計算し、足りない設定を止める")
def _():
    vt = visibility_timeout_of(celery_app)
    eq(vt, 3600, "いまの可視性タイムアウト（既定値）")
    eq(ensure_visibility(JobSettings(work_seconds=1.0), 14, vt), 22.0, "既定の設定（待ち8秒＋14日×1秒）")
    eq(worst_message_seconds(JobSettings(work_seconds=300.0), 14), 4208.0, "1日5分かかる場合")
    try:
        ensure_visibility(JobSettings(work_seconds=300.0), 14, vt)
        raise AssertionError("ValueError になるはず")
    except ValueError as e:
        assert "8416" in str(e), str(e)
    return "既定 22 秒（3600 秒に収まる）・1日5分なら 4208 秒 → 8416 秒が必要で ValueError"


@dbcheck("P3 進捗を受け取りながら結果を待つクライアント")
async def _():
    async with overrides(app, clock=CLOCK, settings=FAST) as redis, serve(app) as base:
        async with httpx2.AsyncClient(base_url=base, timeout=30) as client:
            job_id = await submit(client, KEY)
            done = await follow_job(client, job_id, bearer(KEY))
            store = JobStore(redis)
            queued = new_job("u002", 7, CLOCK, FAST, "req_verify")
            await store.create(queued, ttl=60)
            await store.cancel(queued.job_id, ttl=60)
            cancelled = await follow_job(client, queued.job_id, bearer(KEY))
            missing = await follow_job(client, new_job("u002", 7, CLOCK, FAST, "x").job_id, bearer(KEY))
    eq(done.progress, [(n, 7) for n in range(8)], "progress")
    eq((done.final, len(done.data["result"]["days"]), done.connections), ("done", 7, 1), "終わり")
    eq((cancelled.progress, cancelled.final, cancelled.data), ([], "cancelled", {"done": 0, "total": 7}), "取り消し")
    eq((missing.final, missing.connections), (None, 1), "無いジョブは1回で諦める")
    return "progress (0,7)〜(7,7) → done（接続1回）・キュー待ちで取り消したジョブは cancelled・無いジョブは1回で諦める"


@dbcheck("P4 1日の途中でも中止フラグに気づき、その日を記録せずに止める")
async def _():
    async with redis_client() as redis:
        store = JobStore(redis)
        job = new_job("u002", 7, CLOCK, JobSettings(work_seconds=2.0), "req_verify")
        await store.create(job, ttl=60)
        task = asyncio.create_task(run_responsive(store, job.job_id, poll=0.1))
        await asyncio.sleep(0.3)
        eq(await store.cancel(job.job_id, ttl=60), "running", "DELETE と同じ操作")
        started = time.monotonic()
        status = await task
        elapsed = time.monotonic() - started
        after = await store.get(job.job_id)
        events = [e.event for e in await store.events(job.job_id)]
        recorded = await store.recorded_days(job.job_id)
    eq((status, after.done, recorded), ("cancelled", 0, {}), "止まったあと")
    eq(events, ["progress", "cancelled"], "イベント")
    assert elapsed < 1.0, elapsed  # 1日分（2秒）を待たずに止まる
    return "1日2秒の処理を 0.3 秒で取り消すと、1秒以内に cancelled・その日は記録しない"


@check("P5 プランごとの保存期限と、retry-after を尊重する再試行")
def _():
    eq([result_ttl_for(p) for p in ("free", "pro", "team")], [3600, 86_400, 3600], "保存期限")
    waits = [decide_with_retry_after(UpstreamRateLimited(30), 0, rand=lambda: 1.0).countdown,
             decide_with_retry_after(UpstreamRateLimited(1), 1, rand=lambda: 1.0).countdown,
             decide_with_retry_after(UpstreamRateLimited(600), 0, rand=lambda: 1.0).countdown,
             decide_with_retry_after(TransientJobError(), 2, rand=lambda: 0.0).countdown]
    eq(waits, [30.0, 4.0, 60.0, 4.0], "待ち秒数")
    eq([decide_with_retry_after(UpstreamRateLimited(1), 3).retry, decide_with_retry_after(ValueError(), 0).retry],
       [False, False], "再試行しないもの")
    return "free 3600・pro 86400・不明 3600 秒／retry-after 30 → 30 秒・1 → 4 秒（バックオフが長い）・600 → 60 秒で頭打ち"


@dbcheck("P6 利用者ごとに同時に動かせるジョブを制限する（free 1・pro 2）")
async def _():
    async with redis_client() as redis:
        active = ActiveJobs(redis)
        free = [await active.acquire("u001", j, 1, 60) for j in ("j1", "j2", "j1")]
        await active.release("u001", "j1")
        after_release = await active.acquire("u001", "j2", 1, 60)
        pro = [await active.acquire("u002", j, 2, 60) for j in ("j1", "j2", "j3")]
        user = CurrentUser("u001", "佐藤 美咲", "free", "key")
        try:
            await admit(active, user, "j9", ttl=60)
            raise AssertionError("429 になるはず")
        except ApiError as e:
            denied = (e.status_code, e.type, e.message, e.headers)
        await redis.delete(active.key("u001"), active.key("u002"))
    eq((free, after_release), ([True, False, True], True), "free（上限1）")
    eq(pro, [True, True, False], "pro（上限2）")
    eq(denied, (429, "rate_limited", MESSAGES["rate_limited"], {"retry-after": "10"}), "断るときの形")
    return "free：1件目 OK・2件目 NG・同じジョブの2回目は OK・終われば次が入る／pro：2件まで／断るときは 429 rate_limited・retry-after 10"


finish("session12-practice")
