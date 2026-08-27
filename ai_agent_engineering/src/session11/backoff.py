#!/usr/bin/env python3
"""指数バックオフと、待機の注入（セッション11）。

教材で `time.sleep()` を直接呼ぶとテストが遅くなり、しかも「本当に待ったか」を
検証できない。時計を注入したのと同じ理由で、**待機も注入する**。

  RecordingSleeper … 待った「ことにして」秒数を記録するだけ（本書の既定）
  RealSleeper      … 実際に待つ（本番用）
"""

from __future__ import annotations

import time

BASE = 0.5     # 1回目の待機（秒）
FACTOR = 2.0   # 何倍ずつ伸ばすか
CAP = 8.0      # 頭打ち（秒）


def backoff_delay(attempt: int, *, base: float = BASE, factor: float = FACTOR,
                  cap: float = CAP, jitter: float = 0.0) -> float:
    """attempt は0始まり。0.5 → 1.0 → 2.0 → 4.0 → 8.0 → 8.0 … と伸びて cap で止まる。

    jitter は本番で必ず入れる（既定 0.0 は教材の決定性のため）。
    同時に落ちた複数のクライアントが同じ間隔で再試行すると、回復した瞬間に
    もう一度同時に殺到する。ずらすための乱数が jitter である。
    """
    if attempt < 0:
        raise ValueError("attempt は0以上で指定してください。")
    return round(min(base * (factor ** attempt), cap) + jitter, 3)


class RecordingSleeper:
    """待った「ことにする」時計係。実時間では待たない。"""

    def __init__(self) -> None:
        self.waits: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.waits.append(round(float(seconds), 3))

    @property
    def total(self) -> float:
        return round(sum(self.waits), 3)

    @property
    def count(self) -> int:
        return len(self.waits)

    def reset(self) -> None:
        self.waits.clear()


class RealSleeper:
    """本番用。演習では使わない（テストが遅くなるため）。"""

    def sleep(self, seconds: float) -> None:  # pragma: no cover - 教材では呼ばない
        time.sleep(seconds)


def delay_table(n: int = 6, **kwargs) -> str:
    """待機の伸び方を表で返す（本文の表の出典）。"""
    lines = ["| 試行 | 待機（秒） | ここまでの合計（秒） |",
             "| ---: | ---: | ---: |"]
    total = 0.0
    for i in range(n):
        d = backoff_delay(i, **kwargs)
        total = round(total + d, 3)
        lines.append(f"| {i + 1} 回目の失敗のあと | {d} | {total} |")
    return "\n".join(lines)


if __name__ == "__main__":
    print(delay_table())
