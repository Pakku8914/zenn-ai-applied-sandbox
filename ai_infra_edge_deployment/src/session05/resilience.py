#!/usr/bin/env python3
"""リトライ・冪等性・サーキットブレーカ（セッション5）。

`infrakit.client.LlamaClient.generate` は**再試行しない**（意図的な欠け）。
その回収をここで行う。ただし「とりあえず3回投げ直す」は上流を殺すので、
再送する条件・回数・間隔・総量をすべて明示的に決める。

時計と乱数は注入できるようにしてある（テストを決定的にするため）。

  docker compose exec app python src/session05/resilience.py
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

# 再試行してよい状態。502/503/504 は「上流の都合」で、同じ要求をもう一度
# 出せば成功しうる。400 系（429 を除く）は要求そのものが悪いので再送しても同じ。
RETRYABLE = frozenset({502, 503, 504})


# ---------------------------------------------------------------------------
# リトライ予算
# ---------------------------------------------------------------------------


@dataclass
class RetryBudget:
    """リトライの総量に上限を設ける。

    「1リクエストにつき最大N回」だけを決めても、障害時には全リクエストが
    再送するので入力が N 倍になる。**全体の何割までを再送に使うか**を決めるのが
    リトライ予算である。
    """

    ratio: float = 0.1
    requests: int = 0
    retries: int = 0

    def record_request(self) -> None:
        self.requests += 1

    def try_retry(self) -> bool:
        """再送してよければ True。予算を消費する。"""
        if self.retries + 1 > self.ratio * self.requests:
            return False
        self.retries += 1
        return True

    @property
    def used_ratio(self) -> float:
        return self.retries / self.requests if self.requests else 0.0


def offered_load_multiplier(attempts: int, budget_ratio: float | None = None) -> float:
    """上流が失敗を返し続けたときに、入力が何倍になるか（最悪値）。

    予算なしなら試行回数そのまま（3回再送＝4倍）。予算があれば 1 + 割合で収まる。
    セッション4の実測では、スロット2 に並列4 を入れた時点で TTFT p50 が
    155ms から 1,772ms に悪化している。飽和した上流に4倍の入力を足す判断が
    どれだけ危ういかは、その数字で考えるとよい。
    """
    if attempts < 1:
        raise ValueError("attempts は 1 以上を指定してください")
    if budget_ratio is None:
        return float(attempts)
    return 1.0 + budget_ratio


# ---------------------------------------------------------------------------
# リトライ方針
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetryPolicy:
    """再送の条件・回数・間隔。

    attempts : 初回を含む試行回数（2 なら再送は1回まで）
    base_ms  : 1回目の待ち時間の基準
    cap_ms   : 待ち時間の上限（指数的に伸ばし続けない）
    jitter   : ばらつきの幅。0.5 なら「上限の 50〜100%」で散らす
    """

    attempts: int = 2
    base_ms: float = 100.0
    cap_ms: float = 2000.0
    jitter: float = 0.5
    retry_on: frozenset[int] = RETRYABLE

    def backoff_ms(self, attempt: int,
                   rng: Callable[[], float] = random.random) -> float:
        """指数バックオフ＋ジッタ。attempt は 0 起点。

        ジッタを入れないと、同時に失敗したクライアントが同時に再送して
        同じ波が繰り返し上流を叩く（thundering herd）。
        """
        raw = min(self.cap_ms, self.base_ms * (2 ** attempt))
        low = raw * (1.0 - self.jitter)
        return low + (raw - low) * rng()

    def should_retry(self, status: int, attempt: int, *, idempotent: bool,
                     budget: RetryBudget | None = None) -> tuple[bool, str]:
        """再送するかを決め、理由も返す（記録に残せるようにするため）。"""
        if attempt + 1 >= self.attempts:
            return False, "試行回数の上限に達している"
        if not idempotent:
            return False, "冪等でない要求は再送しない"
        if status == 429:
            return False, "429 は上流が『速すぎる』と言っている。再送せず呼び出し元に返す"
        if status not in self.retry_on:
            return False, f"{status} は再試行の対象ではない"
        if budget is not None and not budget.try_retry():
            return False, "リトライ予算を使い切っている"
        return True, "再試行する"


@dataclass(frozen=True)
class TimeoutPlan:
    """タイムアウトの多層化。

    外側（クライアント）から内側（上流1回分）へ、必ず短くなっていく。
    内側が外側より長いと、クライアントが諦めた後も上流は計算を続ける
    （＝誰も受け取らない出力に CPU を使う）。
    """

    client_ms: float
    gateway_ms: float
    per_try_ms: float
    attempts: int = 2
    backoff_total_ms: float = 0.0

    @property
    def worst_case_ms(self) -> float:
        return self.per_try_ms * self.attempts + self.backoff_total_ms

    def problems(self) -> list[str]:
        issues: list[str] = []
        if self.gateway_ms >= self.client_ms:
            issues.append("ゲートウェイのタイムアウトがクライアント以上になっている")
        if self.worst_case_ms > self.gateway_ms:
            issues.append("再送を含めた最悪時間がゲートウェイの上限を超える")
        return issues


def per_try_timeout_ms(gateway_ms: float, attempts: int,
                       backoff_total_ms: float = 0.0) -> float:
    """ゲートウェイの上限から逆算した、1回分のタイムアウト。"""
    if attempts < 1:
        raise ValueError("attempts は 1 以上を指定してください")
    room = gateway_ms - backoff_total_ms
    if room <= 0:
        raise ValueError("待ち時間だけで上限を使い切っています")
    return room / attempts


# ---------------------------------------------------------------------------
# 冪等性
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Lease:
    """冪等キーの引き当て結果。

    state == "new"       : この呼び出しが実行してよい
    state == "in_flight" : 同じキーが処理中（409 で断る）
    state == "done"      : 済んでいるので保存した応答をそのまま返す
    """

    state: str
    response: dict | None = None
    status_code: int = 0


@dataclass
class IdempotencyStore:
    """冪等キーごとに「処理中」と「結果」を覚えておく。

    リトライと組み合わせて初めて意味を持つ。再送のたびに生成し直すと、
    課金・監査記録・下流への書き込みが二重になる。
    """

    ttl_seconds: float = 300.0
    clock: Callable[[], float] = time.monotonic
    entries: dict[str, tuple[str, float, dict | None]] = field(default_factory=dict)

    def begin(self, key: str) -> Lease:
        now = self.clock()
        entry = self.entries.get(key)
        if entry is not None and now - entry[1] > self.ttl_seconds:
            # 期限切れ。処理中のまま落ちたリクエストが永久に居座るのを防ぐ
            self.entries.pop(key, None)
            entry = None
        if entry is None:
            self.entries[key] = ("in_flight", now, None)
            return Lease("new")
        state, _, response = entry
        if state == "in_flight":
            return Lease("in_flight", None, 409)
        return Lease("done", response)

    def complete(self, key: str, response: dict) -> None:
        self.entries[key] = ("done", self.clock(), response)

    def fail(self, key: str) -> None:
        """失敗したら記録を消す。消さないと再送が永久に 409 になる。"""
        self.entries.pop(key, None)


# ---------------------------------------------------------------------------
# サーキットブレーカ
# ---------------------------------------------------------------------------


@dataclass
class CircuitBreaker:
    """上流が壊れているときに、叩き続けるのをやめる仕組み。

    closed（通す）→ 失敗が続く → open（通さない）→ 冷却後 → half_open
    （試しに通す）→ 成功が続けば closed、1回でも失敗すれば open。

    本書の実装は half_open で通す本数を絞っていない。実務では同時に流す
    プローブを1本に限るのが普通である。
    """

    failure_threshold: int = 5
    cooldown_s: float = 10.0
    success_threshold: int = 2
    clock: Callable[[], float] = time.monotonic
    state: str = "closed"
    failures: int = 0
    successes: int = 0
    opened_at: float = 0.0

    def allow(self) -> bool:
        """いま上流を呼んでよいか。open のまま冷却が明けたら half_open にする。"""
        if self.state == "open":
            if self.clock() - self.opened_at >= self.cooldown_s:
                self.state = "half_open"
                self.successes = 0
                return True
            return False
        return True

    def retry_after_s(self) -> float:
        """open のとき、あと何秒待てばよいか（503 の `Retry-After` に入れる）。"""
        if self.state != "open":
            return 0.0
        return max(self.cooldown_s - (self.clock() - self.opened_at), 0.0)

    def record(self, ok: bool) -> None:
        if ok:
            if self.state == "half_open":
                self.successes += 1
                if self.successes >= self.success_threshold:
                    self._close()
            else:
                self.failures = 0
            return
        if self.state == "half_open":
            self._open()          # 試した1本が失敗したら、すぐ閉める
            return
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self._open()

    def _open(self) -> None:
        self.state = "open"
        self.opened_at = self.clock()
        self.failures = self.failure_threshold
        self.successes = 0

    def _close(self) -> None:
        self.state = "closed"
        self.failures = 0
        self.successes = 0


if __name__ == "__main__":
    policy = RetryPolicy()
    print("=== バックオフ（base=100ms / cap=2000ms / jitter=0.5・rng は 0.5 固定）===")
    for attempt in range(6):
        low = policy.backoff_ms(attempt, rng=lambda: 0.0)
        mid = policy.backoff_ms(attempt, rng=lambda: 0.5)
        high = policy.backoff_ms(attempt, rng=lambda: 1.0)
        print(f"{attempt} 回目の待ち: {mid:.0f} ms（範囲 {low:.0f}〜{high:.0f} ms）")

    print()
    print("=== 上流が失敗し続けたときの入力の倍率（最悪値）===")
    print(f"再送3回・予算なし     : {offered_load_multiplier(4):.1f} 倍")
    print(f"再送1回・予算なし     : {offered_load_multiplier(2):.1f} 倍")
    print(f"予算 10% を付けた場合 : {offered_load_multiplier(4, 0.1):.1f} 倍")
