#!/usr/bin/env python3
"""セッション5の練習問題の解答を自己検証する。

解答章に載せた数値（問題2の手計算表・問題5の条件Y・問題6のタイムアウトと
予算・問題9の振り分け）が、実装の出力と一致することを確かめる。
サーバを使わないので数秒で終わる。期待値と違えば非0で終了する。

  docker compose exec app python src/session05/verify_practice.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from gateway_policy import KeyedRateLimiter, SimConfig, simulate  # noqa: E402
from resilience import (  # noqa: E402
    RetryBudget, TimeoutPlan, offered_load_multiplier, per_try_timeout_ms,
)
from routing import route  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def near(a: float, b: float) -> bool:
    return abs(a - b) < 1e-9


# --- 問題2：トークンバケットの手計算表 --------------------------------------
print("=== 問題2 トークンバケットの手計算（rate=2 / burst=4）===")
clock = {"t": 0.0}
limiter = KeyedRateLimiter(rate=2.0, burst=4.0, clock=lambda: clock["t"])

# (到着時刻, 通るか, 判定後の残り, Retry-After)
TABLE = [
    (0.0, True, 3.0, 0.0),
    (0.0, True, 2.0, 0.0),
    (0.0, True, 1.0, 0.0),
    (0.0, True, 0.0, 0.0),
    (0.0, False, 0.0, 0.5),
    (0.3, False, 0.6, 0.2),
    (1.0, True, 1.0, 0.0),
    (10.0, True, 3.0, 0.0),
]
for i, (t, allowed, left, retry_after) in enumerate(TABLE, start=1):
    clock["t"] = t
    d = limiter.check("tenant-a")
    check(f"問題2 #{i}（t={t:.2f}s）",
          d.allowed is allowed and near(d.tokens_left, left)
          and near(d.retry_after_s, retry_after),
          f"{'200' if d.allowed else '429'} / 残り {d.tokens_left:.2f} / "
          f"Retry-After {d.retry_after_s:.2f}s")

# --- 問題5：条件Y（到着 600ms 間隔）では構成の差が出ない --------------------
print("\n=== 問題5 条件Y（到着 600ms 間隔・スロット2・1件1,000ms）===")
slow_arrivals = [float(i * 600) for i in range(8)]
configs = [
    SimConfig("キューなし", slots=2, service_ms=1000.0, queue_limit=0),
    SimConfig("キュー上限2", slots=2, service_ms=1000.0, queue_limit=2),
    SimConfig("キュー無制限", slots=2, service_ms=1000.0, queue_limit=99),
    SimConfig("無制限＋期限1000ms", slots=2, service_ms=1000.0, queue_limit=99,
              deadline_ms=1000.0),
]
results = [simulate(slow_arrivals, cfg) for cfg in configs]
for r in results:
    print(f"  {r.label:<20} 受け {r.accepted} / 断り {r.rejected} / 期限切れ "
          f"{r.expired} / p95 {r.latency['p95']:.0f}ms")
check("問題5 条件Yでは全構成が8件を受ける",
      all(r.accepted == 8 and r.rejected == 0 and r.expired == 0 for r in results),
      "入力が処理能力を下回っていればキューは伸びない")
check("問題5 条件Yでは p95 も同じ（待ちが発生しない）",
      all(near(r.latency["p95"], 1000.0) for r in results),
      "設計判断が要るのは飽和しているときだけ")

fast_arrivals = [float(i * 250) for i in range(8)]
x_none = simulate(fast_arrivals, configs[0])
check("問題5 条件Xでは同じ構成が半分を断る",
      x_none.accepted == 4 and x_none.rejected == 4,
      f"成功率 {x_none.success_rate * 100:.0f}%（条件Yでは 100%）")

# --- 問題6：タイムアウトの逆算とリトライ予算 ---------------------------------
print("\n=== 問題6 タイムアウトとリトライ予算 ===")
per_try = per_try_timeout_ms(7500, attempts=2, backoff_total_ms=200)
check("問題6 1回分は 3,650ms", near(per_try, 3650.0), f"{per_try:.0f}ms")
plan = TimeoutPlan(client_ms=8000, gateway_ms=7500, per_try_ms=per_try,
                   attempts=2, backoff_total_ms=200)
check("問題6 3階層が破綻しない", plan.problems() == [],
      f"最悪 {plan.worst_case_ms:.0f}ms ≦ ゲートウェイ {plan.gateway_ms:.0f}ms "
      f"< クライアント {plan.client_ms:.0f}ms")

budget = RetryBudget(ratio=0.05)
for _ in range(1000):
    budget.record_request()
granted = sum(1 for _ in range(100) if budget.try_retry())
check("問題6 1,000 リクエスト・予算5% なら再送は 50 回まで", granted == 50,
      f"許可 {granted} 回（使用率 {budget.used_ratio:.3f}）")
check("問題6 試行2回（再送1回）は入力を2倍、予算5% なら 1.05 倍",
      near(offered_load_multiplier(2), 2.0)
      and near(offered_load_multiplier(2, 0.05), 1.05),
      "飽和した上流に2倍を足すか、5% 増で収めるか")

# --- 問題9：振り分けの6ケース -----------------------------------------------
print("\n=== 問題9 振り分けの6ケース ===")
CASES = [
    (200, 64, "interactive", False, "fast", 64, False, 0),
    (200, 200, "interactive", False, "quality", 200, False, 0),
    (200, 200, "batch", False, "fast", 64, True, 0),
    (200, 64, "interactive", True, "fast", 64, True, 0),
    (950, 200, "batch", True, "fast", 64, True, 0),
    (1200, 64, "interactive", False, "-", 0, False, 413),
]
for i, (tokens, want, priority, busy, tier, granted_max, degraded, code) in enumerate(
        CASES, start=1):
    r = route(tokens, want, priority=priority, upstream_degraded=busy)
    check(f"問題9 ケース{i}",
          r.tier == tier and r.max_tokens == granted_max
          and r.degraded is degraded and r.status_code == code,
          f"{r.tier} / max_tokens {r.max_tokens} / 縮退 {r.degraded} / "
          f"status {r.status_code}")

swapped = route(950, 200, priority="batch", upstream_degraded=True)
check("問題9 判定順序を入れ替えても結果は同じ（変わるのは理由の記録）",
      swapped.tier == "fast" and swapped.max_tokens == 64 and swapped.degraded,
      "両方の条件が同時に成立し、結論が一致するケースだから")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション5の練習問題の検証はすべて成功しました。")
