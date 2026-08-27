#!/usr/bin/env python3
"""セッション5の自己検証（その2）：再送しても壊さないこと。

- 指数バックオフ＋ジッタ（乱数を注入して決定的に）
- 再送してよい条件（429 は再送しない・冪等でない要求は再送しない）
- リトライ予算（障害時に入力が何倍になるかを抑える）
- タイムアウトの多層化（内側が外側より長い設定を検出する）
- 冪等キー（処理中は 409・完了済みは保存した応答）
- サーキットブレーカの状態遷移（時計を注入して決定的に）

**推論サーバは不要**。

  docker compose exec app python src/session05/verify_resilience.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from resilience import (  # noqa: E402
    CircuitBreaker, IdempotencyStore, RetryBudget, RetryPolicy, TimeoutPlan,
    offered_load_multiplier, per_try_timeout_ms,
)

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


policy = RetryPolicy()

# --- 1. バックオフ ----------------------------------------------------------
print("=== バックオフ（base=100ms / cap=2000ms / jitter=0.5）===")
mids = [policy.backoff_ms(i, rng=lambda: 0.5) for i in range(6)]
check("待ち時間が指数的に伸びる", mids == [75.0, 150.0, 300.0, 600.0, 1200.0, 1500.0],
      " / ".join(f"{m:.0f}ms" for m in mids))
check("上限で打ち止めになる", policy.backoff_ms(9, rng=lambda: 1.0) == 2000.0,
      "9 回目でも cap の 2,000ms を超えない")
check("ジッタの幅は上限の 50〜100%",
      policy.backoff_ms(1, rng=lambda: 0.0) == 100.0
      and policy.backoff_ms(1, rng=lambda: 1.0) == 200.0,
      "1 回目は 100〜200ms に散る（同時再送を防ぐ）")

# --- 2. 再送してよい条件 ----------------------------------------------------
print("\n=== 再送の判定 ===")
ok, why = policy.should_retry(503, attempt=0, idempotent=True)
check("503 は再送する", ok, why)
ok, why = policy.should_retry(429, attempt=0, idempotent=True)
check("429 は再送しない", not ok, why)
ok, why = policy.should_retry(400, attempt=0, idempotent=True)
check("400 は再送しない", not ok, why)
ok, why = policy.should_retry(503, attempt=0, idempotent=False)
check("冪等でない要求は再送しない", not ok, why)
ok, why = policy.should_retry(503, attempt=1, idempotent=True)
check("試行回数の上限で打ち止める", not ok, why)

# --- 3. リトライ予算 --------------------------------------------------------
print("\n=== リトライ予算（全体の 10% まで）===")
budget = RetryBudget(ratio=0.1)
for _ in range(100):
    budget.record_request()
granted = sum(1 for _ in range(20) if budget.try_retry())
check("100 リクエストなら再送は 10 回まで", granted == 10,
      f"許可 {granted} 回 / 要求 20 回（使用率 {budget.used_ratio:.2f}）")

small = RetryBudget(ratio=0.1)
for _ in range(10):
    small.record_request()
first, why1 = policy.should_retry(503, attempt=0, idempotent=True, budget=small)
second, why2 = policy.should_retry(503, attempt=0, idempotent=True, budget=small)
check("予算を使い切ったら再送しない", first and not second, f"1回目: {why1} / 2回目: {why2}")

check("再送3回は入力を4倍にする", offered_load_multiplier(4) == 4.0,
      "飽和した上流に4倍を足すと、待ち時間だけが伸びる（セッション4の実測）")
check("予算を付ければ 1.1 倍で収まる",
      abs(offered_load_multiplier(4, 0.1) - 1.1) < 1e-9, "1 + 予算 10%")

# --- 4. タイムアウトの多層化 ------------------------------------------------
print("\n=== タイムアウトの多層化 ===")
bad = TimeoutPlan(client_ms=10000, gateway_ms=12000, per_try_ms=6000,
                  attempts=2, backoff_total_ms=150)
check("内側が外側より長い設定を検出する", len(bad.problems()) == 2,
      " / ".join(bad.problems()))
per_try = per_try_timeout_ms(9000, attempts=2, backoff_total_ms=150)
check("ゲートウェイの上限から1回分を逆算できる", per_try == 4425.0, f"{per_try:.0f}ms")
good = TimeoutPlan(client_ms=10000, gateway_ms=9000, per_try_ms=per_try,
                   attempts=2, backoff_total_ms=150)
check("逆算した値なら破綻しない", good.problems() == [],
      f"最悪 {good.worst_case_ms:.0f}ms ≦ ゲートウェイ {good.gateway_ms:.0f}ms")

# --- 5. 冪等キー ------------------------------------------------------------
print("\n=== 冪等キー ===")
now = {"t": 0.0}
store = IdempotencyStore(ttl_seconds=60.0, clock=lambda: now["t"])
first_lease = store.begin("req-001")
check("初回は実行してよい", first_lease.state == "new", first_lease.state)
dup = store.begin("req-001")
check("処理中の再送は 409 で断る",
      dup.state == "in_flight" and dup.status_code == 409,
      "同じキーで二重に生成させない")
store.complete("req-001", {"text": "有給は3営業日前までです"})
done = store.begin("req-001")
check("完了済みなら保存した応答を返す（上流を呼ばない）",
      done.state == "done" and done.response == {"text": "有給は3営業日前までです"},
      str(done.response))
now["t"] = 61.0
check("TTL を過ぎたら作り直せる", store.begin("req-001").state == "new",
      "記録を永久に残すとメモリが増え続ける")
store.fail("req-002")
store.begin("req-003")
store.fail("req-003")
check("失敗したら記録を消して再送できるようにする",
      store.begin("req-003").state == "new", "消さないと永久に 409 になる")

# --- 6. サーキットブレーカ --------------------------------------------------
print("\n=== サーキットブレーカ（失敗3回で開く・冷却5秒・成功2回で閉じる）===")
clock = {"t": 0.0}
breaker = CircuitBreaker(failure_threshold=3, cooldown_s=5.0, success_threshold=2,
                         clock=lambda: clock["t"])
breaker.record(False)
breaker.record(False)
check("失敗が閾値未満なら通し続ける",
      breaker.state == "closed" and breaker.allow(),
      f"failures={breaker.failures} / state={breaker.state}")
breaker.record(False)
check("閾値に達すると開く", breaker.state == "open" and not breaker.allow(),
      f"state={breaker.state} / Retry-After {breaker.retry_after_s():.1f}s")
clock["t"] = 2.0
check("冷却中は待つべき秒数を返す", abs(breaker.retry_after_s() - 3.0) < 1e-9,
      f"{breaker.retry_after_s():.1f}s")
clock["t"] = 5.0
check("冷却が明けたら試しに1本通す（half_open）",
      breaker.allow() and breaker.state == "half_open", f"state={breaker.state}")
breaker.record(False)
check("試した1本が失敗したらすぐ閉める", breaker.state == "open",
      f"state={breaker.state} / 冷却が 5.0 秒から再スタートする")
clock["t"] = 10.0
breaker.allow()
breaker.record(True)
check("成功1回では閉じない（たまたま通っただけかもしれない）",
      breaker.state == "half_open", f"successes={breaker.successes}")
breaker.record(True)
check("成功が閾値に達したら閉じる",
      breaker.state == "closed" and breaker.failures == 0, f"state={breaker.state}")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション5（再送と遮断）の検証はすべて成功しました。")
