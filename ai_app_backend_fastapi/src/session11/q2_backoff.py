"""練習問題2の解答：SDK の待ち方の再現・締め切りが無いときの最悪の時間・締め切りまでに始められる試行の数。"""

from __future__ import annotations

from .retry import RetryPolicy, backoff_delay

SDK_INITIAL, SDK_MAX = 0.5, 8.0  # anthropic/_constants.py の INITIAL_RETRY_DELAY・MAX_RETRY_DELAY


def sdk_delay(retry_index: int, rand: float) -> float:
    """anthropic SDK の待ち方：天井付きの指数に (1 - 0.25×乱数) を掛ける（最大 25% だけ短くする）。"""
    return min(SDK_INITIAL * 2.0 ** (retry_index - 1), SDK_MAX) * (1 - 0.25 * rand)


def worst_case_seconds(policy: RetryPolicy, attempt_timeout: float) -> float:
    """締め切りが無いとき、全試行がタイムアウトまで待たされた場合の合計秒（待ちはジッタの上限で数える）。"""
    waits = sum(backoff_delay(i, policy, lambda: 1.0) for i in range(1, policy.max_attempts))
    return waits + policy.max_attempts * attempt_timeout


def attempts_before_deadline(policy: RetryPolicy, deadline_seconds: float, attempt_seconds: float) -> int:
    """各試行が attempt_seconds で失敗するとき、締め切りまでに始められる試行の数（retry_call と同じ判断）。"""
    remaining = deadline_seconds
    for number in range(1, policy.max_attempts + 1):
        remaining -= min(attempt_seconds, remaining)  # 1回の試行には残り時間しか渡さない
        if number == policy.max_attempts:
            return number
        delay = backoff_delay(number, policy, lambda: 1.0)
        if delay >= remaining:
            return number  # 待っても間に合わないので、待たずに諦める
        remaining -= delay
    return policy.max_attempts
