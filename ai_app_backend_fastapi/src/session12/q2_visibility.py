"""練習問題2の解答：1つのメッセージが ack されるまでの最悪の時間を計算し、可視性タイムアウトが足りなければ起動時に止める。"""

from __future__ import annotations

from celery import Celery

from .app import JobSettings
from .runner import BACKOFF_BASE, BACKOFF_CAP, MAX_RETRIES

REDIS_DEFAULT_VISIBILITY = 3600  # kombu の Redis トランスポートの既定値（秒）


def max_countdown() -> float:
    """再試行の待ちの最大値（最後の再試行のジッタの上限）。"""
    return min(BACKOFF_CAP, BACKOFF_BASE * 2 ** (MAX_RETRIES - 1))


def worst_message_seconds(settings: JobSettings, max_days: int) -> float:
    """worker がメッセージを受け取ってから ack するまでの最悪の時間。

    countdown 付きの再試行メッセージは、待っている間も worker が受け取ったまま（未 ack）で持つ。
    そのため「待ち」と「全日分の処理」を足したものが、1つのメッセージの最悪の時間になる。
    """
    return max_countdown() + max_days * settings.work_seconds


def visibility_timeout_of(app: Celery) -> int:
    return int(app.conf.broker_transport_options.get("visibility_timeout", REDIS_DEFAULT_VISIBILITY))


def ensure_visibility(settings: JobSettings, max_days: int, visibility_timeout: int, *,
                      safety: float = 2.0) -> float:
    """最悪の時間の safety 倍が可視性タイムアウトに収まらなければ ValueError。収まれば最悪の時間を返す。"""
    worst = worst_message_seconds(settings, max_days)
    if worst * safety > visibility_timeout:
        raise ValueError(f"可視性タイムアウト {visibility_timeout} 秒では足りません"
                         f"（最悪 {worst:g} 秒の {safety:g} 倍 = {worst * safety:g} 秒が必要）")
    return worst
