#!/usr/bin/env python3
"""ゲートウェイの受け入れ制御（セッション5）。

- キー別のトークンバケット（レート制限）と `Retry-After` の計算
- 受け入れ判定（走らせる / 待たせる / 断る）
- キューの持ち方を変えたときの p95 と成功率を比べる決定的なシミュレーション

**時計は注入できるようにしてある。** 時間に依存する挙動を教材で示すときは、
HTTP 越しに連打して数えるのではなく、注入した時計で決定的に確かめる
（`gateway/main.py` の `TokenBucket` は `time.monotonic()` を直接読むため、
HTTP 経由では 200 の件数が実行ごとに変わる）。

  docker compose exec app python src/session05/gateway_policy.py
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from infrakit.load import percentiles  # noqa: E402

# ---------------------------------------------------------------------------
# レート制限（キー別トークンバケット）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RateDecision:
    """レート制限の判定結果。

    allowed       : 通してよいか
    retry_after_s : 断るとき、何秒後なら通るか（429 の `Retry-After` に入れる）
    tokens_left   : 判定後に残っているトークン数
    """

    allowed: bool
    retry_after_s: float
    tokens_left: float


class KeyedRateLimiter:
    """キーごとに独立したトークンバケットを持つレート制限。

    `gateway/main.py` の `TokenBucket` は**プロセス全体で1個**なので、1つの
    テナントが暴走すると全員が 429 になる。ここではキー（テナント・APIキー・
    IPなど）ごとにバケットを分け、断るときは待つべき秒数まで返す。
    """

    def __init__(self, rate: float, burst: float,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if rate <= 0 or burst < 1:
            raise ValueError("rate は正の数、burst は 1 以上を指定してください")
        self.rate = rate
        self.burst = burst
        self.clock = clock
        # key -> (残りトークン, 最後に更新した時刻)
        self._state: dict[str, tuple[float, float]] = {}

    def check(self, key: str, cost: float = 1.0) -> RateDecision:
        now = self.clock()
        tokens, updated = self._state.get(key, (self.burst, now))
        # 経過時間ぶんだけ補充する。上限は burst（貯め込ませない）
        tokens = min(self.burst, tokens + (now - updated) * self.rate)
        if tokens >= cost:
            self._state[key] = (tokens - cost, now)
            return RateDecision(True, 0.0, tokens - cost)
        # 足りないぶんが補充されるまでの秒数。これを伝えないとクライアントは
        # 「いつ再送すればよいか」が分からず、即座に再送して事態を悪化させる
        self._state[key] = (tokens, now)
        return RateDecision(False, (cost - tokens) / self.rate, tokens)

    def keys(self) -> list[str]:
        return sorted(self._state)


# ---------------------------------------------------------------------------
# 受け入れ判定（バックプレッシャ）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateLimits:
    """入口で持つ上限。

    max_inflight      : 同時に上流へ流す本数。**上流の並列スロット数に合わせる**
    max_queue         : 待たせる本数。0 なら待たせず即座に断る
    queue_deadline_ms : 待ち行列に置いておける上限（超えたら実行しない）
    """

    max_inflight: int = 2
    max_queue: int = 0
    queue_deadline_ms: float = 1000.0


@dataclass(frozen=True)
class GateDecision:
    action: str        # "run" | "queue" | "reject"
    status_code: int   # run / queue はまだ応答しないので 0、reject は 503
    reason: str = ""


def decide(inflight: int, queued: int, limits: GateLimits) -> GateDecision:
    """いま来たリクエストを走らせるか、待たせるか、断るかを決める。

    レート制限（429）を通過した後の判定である。429 は「あなたが速すぎる」、
    503 は「こちらが手一杯」で、意味が違うので分けて扱う。
    """
    if inflight < limits.max_inflight:
        return GateDecision("run", 0, "空きスロットがある")
    if queued < limits.max_queue:
        return GateDecision("queue", 0, f"待たせる（待ち {queued + 1} 件目）")
    return GateDecision("reject", 503, "処理中と待ちが上限に達している")


# ---------------------------------------------------------------------------
# キューの持ち方を比べるシミュレーション（決定的）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimConfig:
    label: str
    slots: int
    service_ms: float
    queue_limit: int
    deadline_ms: float | None = None


@dataclass(frozen=True)
class SimResult:
    label: str
    accepted: int
    rejected: int      # 入口で断った（待たせてもいない）
    expired: int       # 待たせた末に期限切れで捨てた
    latency: dict[str, float]

    @property
    def offered(self) -> int:
        return self.accepted + self.rejected + self.expired

    @property
    def success_rate(self) -> float:
        return self.accepted / self.offered if self.offered else 0.0


def simulate(arrivals_ms: Sequence[float], cfg: SimConfig) -> SimResult:
    """到着列を与えて、受けた件数・断った件数・応答時間の分布を返す。

    1件あたりの処理時間を固定（`service_ms`）にしてあるので、実行しても
    数字がぶれない。**実測ではなく設計判断のための思考実験**である。
    パーセンタイルの定義はセッション2の `infrakit.load.percentiles` と共通。
    """
    free_at = [0.0] * cfg.slots
    queue: list[float] = []
    latencies: list[float] = []
    rejected = 0
    expired = 0

    def start_ready(now: float) -> None:
        """空いたスロットに待ち行列から詰める（`now` より先の未来は動かさない）。"""
        nonlocal expired
        while queue:
            i = min(range(cfg.slots), key=lambda k: free_at[k])
            if free_at[i] > now:
                break
            arrival = queue.pop(0)
            start = max(free_at[i], arrival)
            if cfg.deadline_ms is not None and start - arrival > cfg.deadline_ms:
                # 取り出す時点で期限切れ。プリフィルを始める前に捨てるのが最も安い
                expired += 1
                continue
            free_at[i] = start + cfg.service_ms
            latencies.append(free_at[i] - arrival)

    for t in arrivals_ms:
        start_ready(t)                       # 完了処理を先に済ませてから到着を扱う
        i = min(range(cfg.slots), key=lambda k: free_at[k])
        if free_at[i] <= t:
            free_at[i] = t + cfg.service_ms
            latencies.append(cfg.service_ms)
        elif len(queue) < cfg.queue_limit:
            queue.append(t)
        else:
            rejected += 1
    start_ready(float("inf"))                # 残りを掃き出す

    return SimResult(cfg.label, len(latencies), rejected, expired, percentiles(latencies))


# 到着は 250ms 間隔で8件。スロット2・1件 1,000ms なので入力は処理能力の2倍
ARRIVALS = [float(i * 250) for i in range(8)]

SCENARIOS = (
    SimConfig("キューなし", slots=2, service_ms=1000.0, queue_limit=0),
    SimConfig("キュー上限2", slots=2, service_ms=1000.0, queue_limit=2),
    SimConfig("キュー無制限", slots=2, service_ms=1000.0, queue_limit=99),
    SimConfig("無制限＋期限1000ms", slots=2, service_ms=1000.0, queue_limit=99,
              deadline_ms=1000.0),
)


def comparison_table(arrivals: Sequence[float] = tuple(ARRIVALS),
                     scenarios: Sequence[SimConfig] = SCENARIOS) -> str:
    """引き継げる形（Markdown の表）で返す。条件を必ず1行目に書く。"""
    head = scenarios[0]
    lines = [f"条件: 到着 {len(arrivals)} 件（{arrivals[1] - arrivals[0]:.0f}ms 間隔）"
             f"／スロット {head.slots}／1件 {head.service_ms:.0f}ms",
             "",
             "| 構成 | 受けた | 入口で断った | 期限切れ | 成功率 | p50 | p95 | 最大 |",
             "| :--- | --: | --: | --: | --: | --: | --: | --: |"]
    for cfg in scenarios:
        r = simulate(arrivals, cfg)
        lines.append(f"| {cfg.label} | {r.accepted} | {r.rejected} | {r.expired} | "
                     f"{r.success_rate * 100:.0f}% | {r.latency['p50']:.0f} ms | "
                     f"{r.latency['p95']:.0f} ms | {r.latency['max']:.0f} ms |")
    return "\n".join(lines)


if __name__ == "__main__":
    now = 0.0
    limiter = KeyedRateLimiter(rate=2.0, burst=4.0, clock=lambda: now)

    print("=== レート制限（rate=2 / burst=4・時計を注入して決定的に）===")
    marks = []
    for _ in range(6):
        d = limiter.check("tenant-a")
        marks.append("200" if d.allowed
                     else f"429(Retry-After={d.retry_after_s:.2f}s)")
    print(" ".join(marks))

    now = 0.5
    a = limiter.check("tenant-a")
    b = limiter.check("tenant-b")
    print(f"0.5 秒後の tenant-a: {'200' if a.allowed else '429'}"
          f"（残り {a.tokens_left:.1f}）")
    print(f"同じ時刻の tenant-b: {'200' if b.allowed else '429'}"
          f"（残り {b.tokens_left:.1f}）")

    print()
    print("=== バックプレッシャの比較（決定的なシミュレーション）===")
    print(comparison_table())
