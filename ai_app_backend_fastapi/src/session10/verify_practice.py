"""Session 10 練習問題の解答の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session10
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from kondate.clock import JST, FixedClock
from kondate.verifykit import check, eq, finish
from src.session10.harness import PROMPT, clear_redis, redis_client
from src.session10.limiter import BucketResult, Limiter, QuotaState
from src.session10.plans import PlanLimits
from src.session10.providers import ChatRequest
from src.session10.q1_fixed_window import FixedWindow
from src.session10.q2_plans import TeamLimitSettings, quota_window
from src.session10.q3_errors import TOO_LARGE, quota_error, rate_limited_error, retry_after_seconds
from src.session10.q4_fit import QuotaShort, reserve_fitting
from src.session10.q5_cooldown import ModelCooldown
from src.session10.q6_sliding_log import SlidingLog

FREE = PlanLimits(10, 20_000)
T0 = datetime(2026, 10, 2, 18, 0, tzinfo=JST)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


async def use(lim: Limiter, user_id: str, tokens: int) -> None:
    """その日の使用量を tokens にしておく（予約してすぐ同じ量で精算する）。"""
    result = await lim.reserve(user_id, FREE, tokens, T0, 600)
    await lim.settle(result.reservation, tokens)


@check("P1 固定窓は窓の境界で上限の2倍を通す（トークンバケットは通さない）")
async def _():
    await clear_redis()
    async with redis_client() as redis:
        fixed, bucket = FixedWindow(redis), Limiter(redis)
        f59 = [await fixed.take("u001", 10, at(59)) for _ in range(11)]
        f60 = [await fixed.take("u001", 10, at(60)) for _ in range(10)]
        b59 = [(await bucket.take_request("u001", FREE, at(59))).allowed for _ in range(11)]
        b60 = [(await bucket.take_request("u001", FREE, at(60))).allowed for _ in range(10)]
    eq((sum(f59), sum(f60), sum(b59), sum(b60)), (10, 10, 10, 0), "18:00:59 と 18:01:00 に通った数")
    return "固定窓：18:00:59 に10回・18:01:00 に10回（1秒で20回）／トークンバケット：10回・0回"


@check("P2 team プランを設定に足し、クォータの日と retry-after を JST で返す")
def _():
    s = TeamLimitSettings()
    eq((s.for_plan("team"), s.for_plan("free")), (PlanLimits(120, 1_000_000), FREE), "既定")
    os.environ["LIMIT_TEAM_TOKENS_PER_DAY"] = "2000000"
    try:
        eq(TeamLimitSettings().for_plan("team"), PlanLimits(120, 2_000_000), "環境変数で上書き")
    finally:
        del os.environ["LIMIT_TEAM_TOKENS_PER_DAY"]
    cases = [
        (FixedClock().now(), ("20261002", 21600)),
        (datetime(2026, 10, 2, 14, 59, 59, tzinfo=timezone.utc), ("20261002", 1)),
        (datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc), ("20261003", 86400)),
    ]
    for now, expected in cases:
        eq(quota_window(now), expected, f"quota_window({now.isoformat()})")
    try:
        quota_window(datetime(2026, 10, 2, 18, 0))
        raise AssertionError("タイムゾーンの無い時刻が通った")
    except ValueError:
        pass
    return "team 120回/分・1000000トークン/日（環境変数で 2000000）・UTC 15:00 は JST の翌日 20261003・naive は ValueError"


@check("P3 拒否の種類で種別とヘッダを分ける（待っても入らない量は 422）")
def _():
    eq([retry_after_seconds(ms) for ms in (0, 1, 999, 1000, 1001, 6000)], [1, 1, 1, 1, 2, 6], "秒への切り上げ")
    rate = rate_limited_error(FREE, BucketResult(False, 0, 6000))
    eq((rate.status_code, rate.type, rate.headers), (429, "rate_limited", {
        "x-ratelimit-limit-requests": "10", "x-ratelimit-remaining-requests": "0", "retry-after": "6"}), "回数")
    state = QuotaState(used=19_000, reserved=500, limit=20_000)
    quota = quota_error(state, 1058, datetime(2026, 10, 2, 23, 59, 59, 500000, tzinfo=JST))
    eq((quota.status_code, quota.type, quota.headers), (429, "quota_exceeded", {
        "x-ratelimit-limit-tokens": "20000", "x-ratelimit-remaining-tokens": "500", "retry-after": "1"}), "量")
    huge = quota_error(QuotaState(0, 0, 20_000), 25_000, T0)
    eq((huge.status_code, huge.type, huge.message, huge.headers), (422, "invalid_request", TOO_LARGE, {}), "上限超え")
    return "0/1/999/1000/1001/6000ms → 1/1/1/1/2/6 秒・回数は rate_limited・量は quota_exceeded（23:59:59.5 → 1秒）・25000 は 422"


@check("P4 残りに合わせて max_tokens を縮めて予約する（256 未満しか残らなければ断る）")
async def _():
    await clear_redis()
    chat = ChatRequest(messages=[{"role": "user", "content": PROMPT}], max_tokens=1024)
    async with redis_client() as redis:
        lim = Limiter(redis)
        res_full, fit_full = await reserve_fitting(lim, "u005", FREE, chat, T0, 600)
        await use(lim, "u001", 19_000)
        res_small, fit_small = await reserve_fitting(lim, "u001", FREE, chat, T0, 600)
        try:
            await reserve_fitting(lim, "u001", FREE, chat, T0, 600)
            raise AssertionError("残り 0 で予約できた")
        except QuotaShort as e:
            short = e.state.remaining
        await use(lim, "u003", 19_710)
        _, fit_edge = await reserve_fitting(lim, "u003", FREE, chat, T0, 600)
        await use(lim, "u004", 19_711)
        try:
            await reserve_fitting(lim, "u004", FREE, chat, T0, 600)
            edge_short = False
        except QuotaShort:
            edge_short = True
    eq((fit_full.max_tokens, res_full.amount), (1024, 1058), "残りが十分")
    eq((fit_small.max_tokens, res_small.amount, short), (966, 1000, 0), "残り 1000")
    eq((fit_edge.max_tokens, edge_short), (256, True), "境界（出力に 256 / 255 残る）")
    return "残り十分 → max_tokens 1024 のまま予約 1058／残り 1000 → 966 に縮めて予約 1000、次は断る／出力に 256 残れば通し 255 なら断る"


@check("P5 上流の待ち時間はモデルごとに持ち、短い retry-after で縮めない")
async def _():
    await clear_redis()
    async with redis_client() as redis:
        cd = ModelCooldown(redis)
        await cd.note_429("model-a", 30, at(0))
        await cd.note_429("model-a", 5, at(1))
        kept = await cd.wait_ms("model-a", at(1))
        other = await cd.wait_ms("model-b", at(1))
        await cd.note_429("model-a", 40, at(1))
        extended = await cd.wait_ms("model-a", at(1))
    eq((kept, other, extended), (29000, 0, 40000), "待ち時間（ミリ秒）")
    return "30秒の後に5秒が来ても 29000ms のまま・別のモデルは 0・40秒が来たら 40000ms に延びる"


@check("P6 スライディング窓（ログ）は直近60秒の回数で判定し、境界でも上限を超えない")
async def _():
    await clear_redis()
    async with redis_client() as redis:
        log = SlidingLog(redis)
        first = [await log.take("u001", 10, at(s)) for s in range(10)]
        denied = await log.take("u001", 10, at(9.5))
        reopened = await log.take("u001", 10, at(60))
        closed = await log.take("u001", 10, at(60.5))
        size = await redis.zcard("s10:q6:u001")
        e59 = [(await log.take("u002", 10, at(59))).allowed for _ in range(10)]
        e60 = [(await log.take("u002", 10, at(60))).allowed for _ in range(10)]
    eq([(r.allowed, r.remaining) for r in first], [(True, 9 - i) for i in range(10)], "1秒おきに10回")
    eq((denied.allowed, denied.retry_after_ms), (False, 50500), "9.5秒")
    eq((reopened.allowed, closed.allowed, closed.retry_after_ms, size), (True, False, 500, 10), "60秒と60.5秒")
    eq((sum(e59), sum(e60)), (10, 0), "境界")
    return "0〜9秒に10回 → 9.5秒は 50500ms 待ち → 60秒で1回空く → 60.5秒は 500ms 待ち・記録は10件・18:00:59 と 18:01:00 で 10回・0回"


finish("session10-practice")
