"""練習問題5の解答：プランごとの保存期限と、上流の retry-after を尊重する再試行の方針。"""

from __future__ import annotations

import random
from collections.abc import Callable

from .runner import BACKOFF_BASE, BACKOFF_CAP, MAX_RETRIES, TRANSIENT, RetryDecision, TransientJobError

RESULT_TTL = {"free": 3600, "pro": 86_400}  # 終わったジョブを残す時間（秒）
DEFAULT_RESULT_TTL = 3600  # 知らないプランは短いほうに倒す


def result_ttl_for(plan: str) -> int:
    return RESULT_TTL.get(plan, DEFAULT_RESULT_TTL)


class UpstreamRateLimited(TransientJobError):
    """上流の 429。retry-after（秒）より早くやり直しても、また断られる。"""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"retry-after={retry_after}")
        self.retry_after = retry_after


def decide_with_retry_after(exc: BaseException, retries: int, *,
                            rand: Callable[[], float] = random.random) -> RetryDecision:
    if not isinstance(exc, TRANSIENT) or retries >= MAX_RETRIES:
        return RetryDecision(False)
    ceiling = min(BACKOFF_CAP, BACKOFF_BASE * 2 ** retries)
    wait = ceiling * (0.5 + rand() / 2)
    if isinstance(exc, UpstreamRateLimited):
        # 上流の指示より早くはやり直さない。ただし極端に長い指示は上限で切る（メッセージを長く抱えないため）
        wait = max(wait, min(exc.retry_after, BACKOFF_CAP))
    return RetryDecision(True, wait)
