"""練習問題3の解答：レート制限とクォータの拒否を、種別とヘッダの違う ApiError にする。"""

from __future__ import annotations

from datetime import datetime

from .errors import ApiError
from .limiter import BucketResult, QuotaState
from .plans import PlanLimits, seconds_until_reset
from .ratelimit import request_headers, token_headers

TOO_LARGE = "1回の要求が1日の上限を超えています。max_tokens を小さくしてください。"


def retry_after_seconds(wait_ms: int) -> int:
    """ミリ秒を秒に切り上げる（整数のまま計算する）。0 秒は返さない。"""
    return max(1, (wait_ms + 999) // 1000)


def rate_limited_error(limits: PlanLimits, result: BucketResult) -> ApiError:
    headers = {**request_headers(limits, result.remaining),
               "retry-after": str(retry_after_seconds(result.retry_after_ms))}
    return ApiError(429, "rate_limited", headers=headers)


def quota_error(state: QuotaState, amount: int, now: datetime) -> ApiError:
    """予約が入らなかったときのエラー。待っても絶対に入らない量なら 429 ではなく 422 にする。"""
    if amount > state.limit:
        return ApiError(422, "invalid_request", TOO_LARGE)
    headers = {**token_headers(state), "retry-after": str(seconds_until_reset(now))}
    return ApiError(429, "quota_exceeded", headers=headers)
