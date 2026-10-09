"""Session 11 練習問題の解答の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session11
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from kondate.clock import FixedClock
from kondate.verifykit import check, eq, finish
from src.session11.breaker import BreakerConfig, CircuitBreaker
from src.session11.fallback import Route, Served
from src.session11.harness import (ASK, LIGHT, Connected, chat, clear_redis, fault_stats, mock_provider, redis_client,
                                   reset_mock, resilient)
from src.session11.idempotency import IdempotencyStore, fingerprint
from src.session11.q1_sdk_retries import measure, upstream_calls
from src.session11.q2_backoff import attempts_before_deadline, sdk_delay, worst_case_seconds
from src.session11.q3_breaker_status import breaker_status
from src.session11.q4_wait_replay import begin_or_wait
from src.session11.q5_meter import FallbackMeter
from src.session11.q6_buffered_prime import buffered_prime
from src.session11.relay import StreamOutcome, relay_chat
from src.session11.retry import RetryPolicy

FP = fingerprint("POST", "/api/ask", ASK)


@check("P1 SDK の自動リトライを stats で数える（529×2 は3回・500×1 は2回・max_retries=0 は1回）")
async def _():
    await reset_mock()
    a = await measure("529", 2, None, "s11-q1-a")
    b = await measure("500", 1, None, "s11-q1-b")
    c = await measure("529", None, 0, "s11-q1-c")
    eq((a.outcome, a.calls, a.retry_counts), ("ok", 3, ["0", "1", "2"]), "529×2・SDK の既定")
    eq((b.outcome, b.calls, b.retry_counts), ("ok", 2, ["0", "1"]), "500×1・SDK の既定")
    eq((c.outcome, c.calls, c.retry_counts), ("overloaded", 1, ["0"]), "529・max_retries=0")
    eq((upstream_calls(2, 3), upstream_calls(0, 3), upstream_calls(2, 1)), (9, 3, 3), "重ねたときの回数")
    return "529×2 → 3回で成功／500×1 → 2回で成功／max_retries=0 → 1回で overloaded／(SDK+1)×自前：2と3で9回"


@check("P2 SDK の待ち方・締め切りが無いときの最悪の時間・締め切りまでに始められる試行の数")
def _():
    eq([sdk_delay(1, 0.0), sdk_delay(1, 1.0), sdk_delay(2, 1.0), sdk_delay(5, 0.0), sdk_delay(6, 0.0)],
       [0.5, 0.375, 0.75, 8.0, 8.0], "SDK の待ち")
    eq((worst_case_seconds(RetryPolicy(max_attempts=3), 30), worst_case_seconds(RetryPolicy(max_attempts=5), 30)),
       (91.5, 157.5), "最悪の時間")
    eq((attempts_before_deadline(RetryPolicy(max_attempts=10), 5, 0),
        attempts_before_deadline(RetryPolicy(max_attempts=10), 20, 3),
        attempts_before_deadline(RetryPolicy(max_attempts=3), 20, 3)), (4, 5, 3), "締め切りまでの試行")
    return ("SDK 1回目 0.375〜0.5秒・5回目以降 6〜8秒／3回×30秒は最悪 91.5秒・5回なら 157.5秒／"
            "締め切り5秒・即失敗なら4回、20秒・3秒で失敗なら5回（5回目は残り0.5秒）")


@check("P3 ブレーカの状態を読むだけで返す（allow を呼ばないので試しの1回を消費しない）")
async def _():
    await clear_redis()
    clock = FixedClock()
    async with redis_client() as redis:
        cb = CircuitBreaker(redis, "primary", BreakerConfig(failure_threshold=3, open_seconds=30))
        fresh = await breaker_status(cb, clock.now())
        for _ in range(3):
            await cb.record_failure(clock.now())
        opened = await breaker_status(cb, clock.now())
        clock.advance(12.5)
        later = await breaker_status(cb, clock.now())
        clock.advance(17.5)
        ready = await breaker_status(cb, clock.now())
        probe = await cb.allow(clock.now())
    eq(fresh, {"route": "primary", "state": "closed", "failures": 0, "retry_in": 0}, "初め")
    eq((opened["state"], opened["failures"], opened["retry_in"], later["retry_in"]), ("open", 3, 30, 18), "開いた後")
    eq((ready["state"], ready["retry_in"], probe.state, probe.allowed), ("open", 0, "half_open", True), "30秒後")
    return "closed・retry_in 0 → 失敗3回で open・retry_in 30 → 12.5秒後 18 → 30秒後 0（読んだだけなので allow で half_open に進める）"


@check("P4 処理中なら待ってから再生する／相手が諦めたら引き継ぐ／締め切りまで決着しなければ in_progress")
async def _():
    await clear_redis()
    async with redis_client() as redis:
        store = IdempotencyStore(redis)

        def scripted(clock: FixedClock, on: dict[int, Callable[[], Awaitable[object]]]) -> tuple[list, Callable]:
            calls: list[float] = []

            async def sleep(seconds: float) -> None:
                calls.append(seconds)
                clock.advance(seconds)
                if len(calls) in on:
                    await on[len(calls)]()
            return calls, sleep

        clock = FixedClock()
        first = await store.begin("u001", "k-done", FP)
        calls1, sleep1 = scripted(clock, {2: lambda: store.complete(first.ticket, 200, '{"text":"ok"}', "light")})
        done = await begin_or_wait(store, "u001", "k-done", FP, clock=clock, sleep=sleep1)

        other = await store.begin("u001", "k-abandon", FP)
        calls2, sleep2 = scripted(clock, {1: lambda: store.abandon(other.ticket)})
        taken = await begin_or_wait(store, "u001", "k-abandon", FP, clock=clock, sleep=sleep2)

        await store.begin("u001", "k-stuck", FP)
        calls3, sleep3 = scripted(clock, {})
        stuck = await begin_or_wait(store, "u001", "k-stuck", FP, clock=clock, timeout=2.0, sleep=sleep3)
        conflict = await begin_or_wait(store, "u001", "k-stuck", "other-fp", clock=clock, sleep=sleep3)
    eq((done.outcome, done.saved.body, done.saved.fallback, calls1), ("replay", '{"text":"ok"}', "light", [0.5, 0.5]),
       "完了を待って再生")
    eq((taken.outcome, taken.ticket is not None, calls2), ("new", True, [0.5]), "諦めた要求を引き継ぐ")
    eq((stuck.outcome, calls3, conflict.outcome), ("in_progress", [0.5, 0.5, 0.5], "conflict"), "決着しない・本文違い")
    return "0.5秒×2回待って replay（fallback=light も再生）／相手が abandon → new で引き継ぐ／2秒で決着せず in_progress（3回待った）／本文違いは待たずに conflict"


@check("P5 経路ごとの応答数を1分単位で数え、直近5分のフォールバック率を出す")
async def _():
    await clear_redis()
    clock = FixedClock()
    async with redis_client() as redis:
        meter = FallbackMeter(redis)
        for route, n in (("primary", 8), ("light", 2)):
            for _ in range(n):
                await meter.record(Served(None, route, [], None if route == "primary" else "overloaded"), clock.now())
        clock.advance(60)
        await meter.record(Served(None, "openai", [], "overloaded"), clock.now())
        now = await meter.ratio(clock.now())
        clock.advance(300)
        gone = await meter.ratio(clock.now())
    eq((now.total, now.fallback, now.ratio, now.by_route, now.alert()),
       (11, 3, 0.273, {"primary": 8, "light": 2, "openai": 1}, True), "直近5分")
    eq((gone.total, gone.ratio, gone.alert()), (0, 0.0, False), "6分後")
    return "primary 8・light 2・openai 1 → フォールバック率 0.273（閾値 0.2 で警告）／6分後は窓の外で 0 件"


@check("P6 先頭18文字まで貯める先読み：差分2個で切れても再試行して完走、primary が切れ続ければ light へ")
async def _():
    await reset_mock()
    await clear_redis()
    two = RetryPolicy(max_attempts=2)
    once = {"x-mock-fault": "disconnect", "x-mock-fault-after": "2", "x-mock-fault-times": "1",
            "x-mock-fault-key": "s11-q6-once"}
    always = {"x-mock-fault": "disconnect", "x-mock-fault-after": "2"}
    async with mock_provider(headers=once, max_retries=0) as flaky, \
            mock_provider(headers=always, max_retries=0) as broken, \
            mock_provider(max_retries=0) as good, redis_client() as redis:
        llm, _ = resilient([Route("primary", flaky, policy=two)], redis, FixedClock())
        served = await buffered_prime(llm, chat(), 18)
        events = [ev.event async for ev in relay_chat(Connected(), served.value,  # type: ignore[arg-type]
                                                      StreamOutcome("req_verify", "m1"))]
        calls = (await fault_stats("s11-q6-once"))["calls"]
        llm2, _ = resilient([Route("primary", broken, policy=two), Route("light", good, LIGHT, two)],
                            redis, FixedClock())
        served2 = await buffered_prime(llm2, chat(), 18)
        events2 = [ev.event async for ev in relay_chat(Connected(), served2.value,  # type: ignore[arg-type]
                                                       StreamOutcome("req_verify", "m2"))]
    eq(([a.outcome for a in served.attempts], calls, events[0], events[-1], "error" in events),
       (["connection", "ok"], 2, "start", "done", False), "1回だけ切れる")
    eq(([f"{a.route}:{a.outcome}" for a in served2.attempts], served2.fallback, events2[-1]),
       (["primary:connection", "primary:connection", "light:ok"], "light", "done"), "切れ続ける")
    return ("差分2個（12文字）で切れても、まだ送っていないので再試行して start…done（上流に2回）／"
            "primary が毎回切れる → primary:connection ×2 → light:ok で done")


finish("session11-practice")
