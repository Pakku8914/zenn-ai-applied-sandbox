#!/usr/bin/env python3
"""セッション5の自己検証（その1）：入口で守れていること。

- キー別トークンバケットが burst 分だけ通し、断るときに待つ秒数を返す
- キーが違えば影響しない（1テナントの暴走で全員が 429 にならない）
- 受け入れ判定が 走らせる / 待たせる / 断る を選び分ける
- キューの持ち方で p95 と成功率がどう動くか（決定的なシミュレーション）

**推論サーバは不要**（時計を注入しているので実行時間にも依存しない）。

  docker compose exec app python src/session05/verify_policy.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from gateway_policy import (  # noqa: E402
    ARRIVALS, SCENARIOS, GateLimits, KeyedRateLimiter, comparison_table, decide,
    simulate,
)

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


# --- 1. キー別のレート制限 ---------------------------------------------------
print("=== レート制限（rate=2 / burst=4・時計を注入）===")
clock = {"t": 0.0}
limiter = KeyedRateLimiter(rate=2.0, burst=4.0, clock=lambda: clock["t"])

allowed = sum(1 for _ in range(6) if limiter.check("tenant-a").allowed)
check("burst 分だけ即座に通る", allowed == 4, f"{allowed} 件 / 6 件（burst=4）")

denied = limiter.check("tenant-a")
check("断るときは待つべき秒数を返す",
      not denied.allowed and abs(denied.retry_after_s - 0.5) < 1e-9,
      f"Retry-After = {denied.retry_after_s:.2f}s（1 トークン ÷ rate 2）")

other = limiter.check("tenant-b")
check("キーが違えば影響を受けない", other.allowed,
      f"tenant-a は枯れているが tenant-b は残り {other.tokens_left:.1f}")

clock["t"] = 0.5
refilled = sum(1 for _ in range(3) if limiter.check("tenant-a").allowed)
check("0.5 秒後に 1 件だけ補充される", refilled == 1,
      f"{refilled} 件（0.5 秒 × rate 2 = 1 トークン）")

clock["t"] = 100.0
capped = sum(1 for _ in range(6) if limiter.check("tenant-a").allowed)
check("長く空けても burst を超えて貯まらない", capped == 4, f"{capped} 件（上限は burst=4）")

# --- 2. 受け入れ判定 --------------------------------------------------------
print("\n=== 受け入れ判定（走らせる / 待たせる / 断る）===")
no_queue = GateLimits(max_inflight=2, max_queue=0)
with_queue = GateLimits(max_inflight=2, max_queue=2)

check("空きがあれば走らせる", decide(1, 0, no_queue).action == "run",
      decide(1, 0, no_queue).reason)
rejected = decide(2, 0, no_queue)
check("キューを持たない構成は即座に 503 で断る",
      rejected.action == "reject" and rejected.status_code == 503, rejected.reason)
queued = decide(2, 0, with_queue)
check("キューを持つ構成は待たせる", queued.action == "queue", queued.reason)
full = decide(2, 2, with_queue)
check("キューが埋まったら断る", full.action == "reject", full.reason)

# --- 3. キューの持ち方と p95 -------------------------------------------------
print("\n=== キューの持ち方（到着8件・スロット2・1件1,000ms）===")
print(comparison_table())

results = {cfg.label: simulate(ARRIVALS, cfg) for cfg in SCENARIOS}
none_q = results["キューなし"]
small_q = results["キュー上限2"]
inf_q = results["キュー無制限"]
deadline_q = results["無制限＋期限1000ms"]

check("キューなし：p95 は最小だが半分を断っている",
      none_q.latency["p95"] == 1000.0 and none_q.accepted == 4 and none_q.rejected == 4,
      f"p95 {none_q.latency['p95']:.0f}ms / 成功率 {none_q.success_rate * 100:.0f}%")
check("キュー上限2：受け付けが増えるぶん p95 が伸びる",
      small_q.accepted == 6 and small_q.latency["p95"] == 2000.0,
      f"受け {small_q.accepted} 件 / p95 {small_q.latency['p95']:.0f}ms")
check("キュー無制限：全件受けるが p95 が最も悪い",
      inf_q.accepted == 8 and inf_q.latency["p95"] == 2500.0,
      f"成功率 {inf_q.success_rate * 100:.0f}% / p95 {inf_q.latency['p95']:.0f}ms")
check("待たせるほど p95 は単調に悪化する",
      none_q.latency["p95"] < small_q.latency["p95"] < inf_q.latency["p95"],
      f"{none_q.latency['p95']:.0f} < {small_q.latency['p95']:.0f} "
      f"< {inf_q.latency['p95']:.0f} ms")
check("期限付きのキューはキューなしより多く受け、無制限より p95 が良い",
      deadline_q.accepted == 6 and deadline_q.expired == 2
      and deadline_q.accepted > none_q.accepted
      and deadline_q.latency["p95"] < inf_q.latency["p95"],
      f"受け {deadline_q.accepted} 件 / 期限切れ {deadline_q.expired} 件 / "
      f"p95 {deadline_q.latency['p95']:.0f}ms")
check("断る場所が違うだけで、捨てる件数は同じになりうる",
      none_q.rejected + none_q.expired == 4
      and small_q.rejected + small_q.expired == deadline_q.rejected + deadline_q.expired,
      "入口で断る（即座に失敗）か、待たせた末に捨てるかの違い")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション5（入口の受け入れ制御）の検証はすべて成功しました。")
