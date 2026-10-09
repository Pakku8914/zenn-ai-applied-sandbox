"""Session 11（リトライ・タイムアウト・フォールバック）の動作確認。api コンテナの中で実行する：

    docker compose exec api python src/session11/verify.py
    docker compose exec api bash verify-all.sh src/session11   # 練習問題の検証も含めて実行
"""

from __future__ import annotations

import time

from kondate.clock import FixedClock
from kondate.verifykit import check, eq, finish, sse_events
from src.session11.app import SCOPE, app
from src.session11.breaker import BreakerConfig, CircuitBreaker
from src.session11.errors import IN_PROGRESS_MESSAGE, MESSAGES
from src.session11.fallback import Route
from src.session11.harness import (ASK, FAKE_TEXT, LIGHT, Connected, assert_error, chat, clear_redis, client_for,
                                   fault_stats, mock_provider, mock_stats, redis_client, reset_mock, resilient)
from src.session11.idempotency import IdempotencyStore, fingerprint
from src.session11.providers import FakeProvider, ProviderError, Usage, fake_script
from src.session11.relay import StreamOutcome, relay_chat
from src.session11.retry import Deadline, FakeSleep, RetryPolicy, backoff_delay, retry_call


def over() -> ProviderError:
    return ProviderError("overloaded", provider="fake", status_code=529)


def ok_script() -> list:
    return fake_script(FAKE_TEXT, usage=Usage(34, 20))


def trail(attempts: list) -> str:
    return " → ".join(f"{a.route}:{a.outcome}" for a in attempts)


@check("V1 SDK の既定（max_retries=2）は 429 を自動で再送する。stats で数えると3回・retry-after に従って2秒")
async def _():
    await reset_mock()
    headers = {"x-mock-fault": "429", "x-mock-fault-times": "2", "x-mock-fault-key": "s11-v1"}
    async with mock_provider(headers=headers) as p:  # max_retries を渡さない＝SDK の既定
        started = time.monotonic()
        result = await p.complete(chat())
        elapsed = time.monotonic() - started
    slot = await fault_stats("s11-v1")
    eq((slot["calls"], slot["injected"], slot["retry_counts"]), (3, 2, ["0", "1", "2"]), "上流が受けた回数")
    assert result.text, "本文が空"
    assert elapsed >= 1.9, f"retry-after を待っていない: {elapsed:.2f} 秒"
    return "429×2 → SDK が3回送って成功・retry_counts ['0', '1', '2']・retry-after: 1 を2回待った（2秒以上）"


@check("V2 二重のリトライ：SDK 2回×自前3回だと上流は9回受ける。SDK を 0 にすれば3回")
async def _():
    await reset_mock()
    clock = FixedClock()
    got = {}
    for label, sdk_retries in (("bad", 2), ("good", 0)):
        key = f"s11-v2-{label}"
        async with mock_provider(headers={"x-mock-fault": "529", "x-mock-fault-key": key},
                                 max_retries=sdk_retries) as p:
            sleep = FakeSleep(clock)
            try:
                await retry_call(lambda budget: p.complete(chat()), policy=RetryPolicy(max_attempts=3),
                                 deadline=Deadline(clock, 20), sleep=sleep, rand=lambda: 1.0)
                raise AssertionError("成功してしまった")
            except ProviderError as e:
                got[label] = (e.kind, (await fault_stats(key))["retry_counts"], sleep.calls)
    eq(got["bad"], ("overloaded", ["0", "1", "2"] * 3, [0.5, 1.0]), "SDK 2回＋自前3回")
    eq(got["good"], ("overloaded", ["0", "0", "0"], [0.5, 1.0]), "SDK 0回＋自前3回")
    return "SDK 2回×自前3回 → 上流に9回（retry_counts 0,1,2 が3巡）／SDK 0回＋自前3回 → 3回（0,0,0）・自前の待ちは 0.5秒→1.0秒"


@check("V3 指数バックオフ＋フルジッタ・retry-after・デッドライン（FakeSleep で実際には待たない）")
async def _():
    p = RetryPolicy()
    eq([backoff_delay(i, p, lambda: 1.0) for i in range(1, 7)], [0.5, 1.0, 2.0, 4.0, 8.0, 8.0], "ジッタ 1.0")
    eq([backoff_delay(i, p, lambda: 0.25) for i in range(1, 4)], [0.125, 0.25, 0.5], "ジッタ 0.25")

    async def run(provider: FakeProvider, policy: RetryPolicy, seconds: float) -> tuple:
        clock = FixedClock()
        sleep, attempts = FakeSleep(clock), []
        try:
            r = await retry_call(lambda budget: provider.complete(chat()), policy=policy,
                                 deadline=Deadline(clock, seconds), sleep=sleep, rand=lambda: 1.0, attempts=attempts)
            result = r.text
        except ProviderError as e:
            result = e.kind
        return result, [a.outcome for a in attempts], sleep.calls

    limited = ProviderError("rate_limited", provider="fake", status_code=429, retry_after=3)
    bad = ProviderError("bad_request", provider="fake", status_code=400)
    eq(await run(FakeProvider([over()], [over()], ok_script()), RetryPolicy(max_attempts=3), 20),
       (FAKE_TEXT, ["overloaded", "overloaded", "ok"], [0.5, 1.0]), "2回失敗して回復")
    eq(await run(FakeProvider([limited], ok_script()), RetryPolicy(), 20),
       (FAKE_TEXT, ["rate_limited", "ok"], [3.0]), "retry-after: 3")
    eq(await run(FakeProvider([over()]), RetryPolicy(max_attempts=10), 5),
       ("overloaded", ["overloaded"] * 4, [0.5, 1.0, 2.0]), "締め切り5秒")
    eq(await run(FakeProvider([bad], ok_script()), RetryPolicy(), 20), ("bad_request", ["bad_request"], []), "400")
    return ("待ちの上限 0.5→1→2→4→8→8 秒（ジッタ 0.25 なら 0.125→0.25→0.5）／529×2 は 0.5秒・1秒待って回復／"
            "retry-after: 3 なら3秒／締め切り5秒：3回待ち、4回目の失敗で諦める（次の4秒は間に合わない）／400 は再試行しない")


@check("V4 ストリーム：最初の差分の前の切断は再試行して完走、差分を送った後の切断は error で終える")
async def _():
    await reset_mock()
    await clear_redis()
    got = {}
    for label, after in (("before", "0"), ("after", "2")):
        key = f"s11-v4-{label}"
        headers = {"x-mock-fault": "disconnect", "x-mock-fault-after": after, "x-mock-fault-times": "1",
                   "x-mock-fault-key": key}
        async with mock_provider(headers=headers, max_retries=0) as p, redis_client() as redis:
            llm, _ = resilient([Route("primary", p)], redis, FixedClock())
            served = await llm.prime(chat())
            outcome = StreamOutcome(request_id="req_verify", message_id="m1")
            events = [ev.event async for ev in relay_chat(Connected(), served.value, outcome)]  # type: ignore[arg-type]
        got[label] = (events, [a.outcome for a in served.attempts], (await fault_stats(key))["calls"],
                      outcome.error_type)
    events, attempts, calls, error_type = got["before"]
    eq((events[0], events[-2:], set(events[1:-2])), ("start", ["usage", "done"], {"delta"}), "再試行して完走")
    eq((attempts, calls, error_type), (["connection", "ok"], 2, None), "before の試行")
    eq(got["after"], (["start", "delta", "delta", "error"], ["ok"], 1, "upstream_unavailable"), "after")
    return ("差分0個で切断 → 再試行して start→delta…→usage→done（上流に2回）／"
            "差分2個のあとで切断 → 再試行せず start→delta→delta→error upstream_unavailable（上流に1回）")


@check("V5 サーキットブレーカ（Redis・Lua）：閉→開→半開。別のサーバも同じ状態を見る")
async def _():
    await clear_redis()
    clock = FixedClock()
    cfg = BreakerConfig(failure_threshold=3, open_seconds=30, probe_seconds=10)
    async with redis_client() as redis:
        a, b = CircuitBreaker(redis, "primary", cfg), CircuitBreaker(redis, "primary", cfg)  # 2台の API サーバ
        fails = [(await a.record_failure(clock.now())).state for _ in range(3)]
        t0 = await b.allow(clock.now())
        clock.advance(29)
        t29 = await b.allow(clock.now())
        clock.advance(1)
        probe, second = await a.allow(clock.now()), await b.allow(clock.now())
        reopened = await a.record_failure(clock.now())
        after_fail = await b.allow(clock.now())
        clock.advance(30)
        probe2 = await a.allow(clock.now())
        clock.advance(10)
        probe3 = await b.allow(clock.now())
        closed = await b.record_success(clock.now())
        last = await a.allow(clock.now())

    def s(x) -> tuple:
        return (x.state, x.allowed)

    eq(fails, ["closed", "closed", "open"], "3回の失敗")
    eq([s(t0), s(t29)], [("open", False), ("open", False)], "開いている間")
    eq([s(probe), s(second)], [("half_open", True), ("half_open", False)], "30秒後")
    eq([reopened.state, s(after_fail)], ["open", ("open", False)], "試しが失敗")
    eq([s(probe2), s(probe3)], [("half_open", True), ("half_open", True)], "試しが戻らない")
    eq([(closed.state, closed.failures), s(last)], [("closed", 0), ("closed", True)], "試しが成功")
    return ("失敗3回で open → 29秒後も拒否 → 30秒後に half_open で1回だけ通す（もう1台は拒否）→ 試しが失敗して open → "
            "30秒後に half_open → 10秒戻らなければ次の1回に任せる → 成功で closed（failures 0）")


@check("V6 フォールバック：primary が2回とも 529 なら light で答えて経路と理由を残す。ブレーカが開けば primary を飛ばす。400 では落とさない")
async def _():
    await clear_redis()
    clock = FixedClock()
    primary, light = FakeProvider([over()]), FakeProvider(ok_script())
    two = RetryPolicy(max_attempts=2)
    async with redis_client() as redis:
        llm, sleep = resilient([Route("primary", primary, policy=two), Route("light", light, LIGHT, two)],
                               redis, clock, breaker=BreakerConfig(failure_threshold=2))
        first = await llm.complete(chat())
        second = await llm.complete(chat())
        await clear_redis()
        bad = FakeProvider([ProviderError("bad_request", provider="fake", status_code=400)])
        llm_bad, _ = resilient([Route("primary", bad), Route("light", light, LIGHT)], redis, clock)
        try:
            await llm_bad.complete(chat())
            raise AssertionError("400 なのにフォールバックした")
        except ProviderError as e:
            bad_kind = e.kind
    eq((first.value.text, first.fallback, first.reason, sleep.calls), (FAKE_TEXT, "light", "overloaded", [0.5]), "1回目")
    eq(trail(first.attempts), "primary:overloaded → primary:overloaded → light:ok", "1回目の試行")
    eq(light.requests[0].model, LIGHT, "light には LLM_MODEL_LIGHT を指定して送る")
    eq((trail(second.attempts), second.reason, len(primary.requests)),
       ("primary:breaker_open → light:ok", "breaker_open", 2), "2回目（ブレーカが開いた後）")
    eq((bad_kind, len(light.requests)), ("bad_request", 2), "400")
    return ("1回目 primary:overloaded → primary:overloaded → light:ok（fallback=light・reason=overloaded・LLM_MODEL_LIGHT）／"
            "2回目 primary:breaker_open → light:ok（primary を呼ばない）／400 は light へ落とさずそのまま返す")


@check("V7 HTTP（mockllm）：primary が 529 なら light で 200。ヘッダ x-kondate-fallback と本文 fallback に残す（SSE も同じ）")
async def _():
    await reset_mock()
    await clear_redis()
    clock = FixedClock()
    two = RetryPolicy(max_attempts=2)
    async with mock_provider(headers={"x-mock-fault": "529"}, max_retries=0) as bad, \
            mock_provider(max_retries=0) as good, redis_client() as redis:
        llm, _ = resilient([Route("primary", bad, policy=two), Route("light", good, LIGHT, two)], redis, clock)
        async with client_for(app, llm, redis) as c:
            r = await c.post("/api/ask", json=ASK)
            s = await c.post("/api/chat/stream", json=ASK)
        stats = await mock_stats()
    events = [e["event"] for e in sse_events(s.text.split("\n"))]
    eq((r.status_code, r.headers.get("x-kondate-fallback"), r.json()["fallback"]), (200, "light", "light"), "/api/ask")
    eq((s.status_code, s.headers.get("x-kondate-fallback"), events[0], events[-1]), (200, "light", "start", "done"), "SSE")
    eq(stats["by_status"], {"529": 4, "200": 2}, "上流の応答")
    return ("/api/ask 200・x-kondate-fallback: light・\"fallback\": \"light\"／/api/chat/stream 200・同じヘッダで start…done／"
            "上流は 529×4・200×2")


@check("V8 3段目の OpenAI 互換まで落ちる。全経路が失敗したら 503 upstream_unavailable（上流の文は返さない）")
async def _():
    await reset_mock()
    await clear_redis()
    clock = FixedClock()
    one = RetryPolicy(max_attempts=1)
    async with mock_provider(headers={"x-mock-fault": "529"}, max_retries=0) as bad, \
            mock_provider("openai", max_retries=0) as oai, \
            mock_provider("openai", headers={"x-mock-fault": "500"}, max_retries=0) as oai_bad, \
            redis_client() as redis:
        ok_llm, _ = resilient([Route("primary", bad, policy=one), Route("light", bad, LIGHT, one),
                               Route("openai", oai, policy=one)], redis, clock)
        async with client_for(app, ok_llm, redis) as c:
            r1 = await c.post("/api/ask", json=ASK)
        await clear_redis()
        ng_llm, _ = resilient([Route("primary", bad, policy=one), Route("light", bad, LIGHT, one),
                               Route("openai", oai_bad, policy=one)], redis, clock)
        async with client_for(app, ng_llm, redis) as c:
            r2 = await c.post("/api/ask", json=ASK)
        stats = await mock_stats()
    eq((r1.status_code, r1.headers.get("x-kondate-fallback"), r1.json()["fallback"]), (200, "openai", "openai"), "3段目")
    assert_error(r2, 503, "upstream_unavailable")
    eq(stats["by_path"], {"/v1/messages": 4, "/v1/chat/completions": 2}, "上流のパス")
    return ("primary 529 → light 529 → openai 200（x-kondate-fallback: openai）／openai も 500 なら 503 upstream_unavailable・"
            "/v1/messages 4回・/v1/chat/completions 2回")


@check("V9 冪等キー：同じキー・同じ本文は再生して上流は1回。本文が違えば 409、処理中も 409、形式違いは 422")
async def _():
    await clear_redis()
    clock = FixedClock()
    fake = FakeProvider(ok_script())
    key = {"Idempotency-Key": "kd-order-0001"}
    async with redis_client() as redis:
        llm, _ = resilient([Route("primary", fake)], redis, clock)
        async with client_for(app, llm, redis) as c:
            first = await c.post("/api/ask", json=ASK, headers=key)
            again = await c.post("/api/ask", json=ASK, headers=key)
            other = await c.post("/api/ask", json={"message": "鮭とほうれん草で作れるものは？"}, headers=key)
            # 処理中の記録を先に作っておく（もう1台のサーバが同じキーを処理している最中を再現する）
            await IdempotencyStore(redis).begin(SCOPE, "kd-order-0002", fingerprint("POST", "/api/ask", ASK))
            busy = await c.post("/api/ask", json=ASK, headers={"Idempotency-Key": "kd-order-0002"})
            malformed = await c.post("/api/ask", json=ASK, headers={"Idempotency-Key": "has space"})
            plain = [await c.post("/api/ask", json=ASK) for _ in range(2)]
    eq((first.status_code, again.status_code, again.text == first.text, again.headers.get("idempotent-replayed")),
       (200, 200, True, "true"), "再生")
    assert_error(other, 409, "idempotency_conflict")
    eq(other.json()["error"]["message"], MESSAGES["idempotency_conflict"], "409 の固定文")
    assert_error(busy, 409, "idempotency_conflict")
    eq((busy.json()["error"]["message"], busy.headers["retry-after"]), (IN_PROGRESS_MESSAGE, "1"), "処理中")
    assert_error(malformed, 422, "invalid_request")
    eq(([r.status_code for r in plain], len(fake.requests)), ([200, 200], 3), "上流に届いた数")
    return ("同じキー・同じ本文 → 2回目は再生（idempotent-replayed: true・本文が一致）／本文違い → 409 idempotency_conflict／"
            "処理中 → 409・retry-after: 1／空白入りのキー → 422／上流はキー付き1回＋キーなし2回の3回")


@check("V10 失敗した要求は記録を消して同じキーでやり直せる。成功の再生ではフォールバックの印も同じ")
async def _():
    await clear_redis()
    clock = FixedClock()
    one = RetryPolicy(max_attempts=1)
    key = {"Idempotency-Key": "kd-order-0003"}
    light = FakeProvider(ok_script())
    async with redis_client() as redis:
        record = IdempotencyStore(redis).record_key(SCOPE, "kd-order-0003")
        down, _ = resilient([Route("primary", FakeProvider([over()]), policy=one)], redis, clock)
        async with client_for(app, down, redis) as c:
            failed = await c.post("/api/ask", json=ASK, headers=key)
        left = await redis.exists(record)
        up, _ = resilient([Route("primary", FakeProvider([over()]), policy=one), Route("light", light, LIGHT)],
                          redis, clock)
        async with client_for(app, up, redis) as c:
            retried = await c.post("/api/ask", json=ASK, headers=key)
            replay = await c.post("/api/ask", json=ASK, headers=key)
        ttl = await redis.pttl(record)
    assert_error(failed, 503, "upstream_unavailable")
    eq(left, 0, "失敗のあとに記録が残っていない")
    eq([(r.status_code, r.headers.get("x-kondate-fallback"), r.json()["fallback"]) for r in (retried, replay)],
       [(200, "light", "light")] * 2, "やり直しと再生")
    eq((replay.headers.get("idempotent-replayed"), len(light.requests)), ("true", 1), "再生では上流を呼ばない")
    assert 86_000_000 < ttl <= 86_400_000, ttl
    return ("503 のあと記録は消える → 同じキーでやり直して 200（light）→ 再生も x-kondate-fallback: light・"
            "light を呼んだのは1回・記録の寿命は24時間")


finish("session11")
