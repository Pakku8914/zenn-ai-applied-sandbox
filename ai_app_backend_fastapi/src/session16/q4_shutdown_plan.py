"""練習問題4：止めるときの3つの時間（DRAIN・GRACEFUL・stop_grace）を、最長のストリームから決める。"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ShutdownPlan:
    drain_grace_seconds: int  # 配信中のストリームに与える猶予（過ぎたら error で閉じる）
    graceful_timeout_seconds: int  # uvicorn --timeout-graceful-shutdown（過ぎたらタスクを打ち切る）
    stop_grace_seconds: int  # docker の stop_grace_period（過ぎたら SIGKILL）

    def as_env(self) -> dict[str, str]:
        return {"DRAIN_GRACE_SECONDS": str(self.drain_grace_seconds),
                "GRACEFUL_TIMEOUT_SECONDS": str(self.graceful_timeout_seconds)}

    def compose_stop_grace(self) -> str:
        return f"{self.stop_grace_seconds}s"


def longest_stream_seconds(max_tokens: int, min_tps: float, ttft_seconds: float) -> float:
    """最も遅い条件で max_tokens まで出し切るときの所要時間（最初の差分まで＋出力の時間）。"""
    if max_tokens < 1 or min_tps <= 0 or ttft_seconds < 0:
        raise ValueError("max_tokens は 1 以上、min_tps は正、ttft_seconds は 0 以上にしてください")
    return ttft_seconds + max_tokens / min_tps


def plan_shutdown(longest_stream: float, *, pre_stop_seconds: int = 0, margin_seconds: int = 5) -> ShutdownPlan:
    """DRAIN < GRACEFUL < stop_grace の順に、margin ずつ離して決める。

    pre_stop_seconds：SIGTERM の前に待つ時間（ロードバランサが行き先から外すのを待つ仕組みがある環境だけ）。
    SIGTERM はその後に届くので、DRAIN と GRACEFUL には足さず、stop_grace にだけ足す。
    """
    if longest_stream <= 0 or pre_stop_seconds < 0 or margin_seconds < 1:
        raise ValueError("longest_stream は正、pre_stop_seconds は 0 以上、margin_seconds は 1 以上にしてください")
    drain = math.ceil(longest_stream)
    graceful = drain + margin_seconds
    return ShutdownPlan(drain, graceful, pre_stop_seconds + graceful + margin_seconds)
