"""問題3：架空の first_audio（20ターン）の平均・p50・p95 を出し、最初の10ターンだけの場合と比べる。

    docker compose exec api python -m src.session12.solutions.q3_percentiles
"""

from __future__ import annotations

import numpy as np

from src.session12.eval_latency import summarize

# 架空の計測値（ミリ秒）。計測した順に並んでいる
FIRST_AUDIO_MS = [
    5620, 5710, 5580, 5840, 5760, 5690, 9120, 5650, 5730, 5800,
    5610, 5770, 5700, 8840, 5680, 5750, 5640, 5720, 5790, 5660,
]


def linear_p95(values: list[int]) -> int:
    """numpy の既定（線形補間）。測っていない値が出ることがある。"""
    return round(float(np.percentile(values, 95)))


def main() -> int:
    print("20ターン：", summarize(FIRST_AUDIO_MS))
    print("最初の10ターン：", summarize(FIRST_AUDIO_MS[:10]))
    print("線形補間の p95（20ターン）：", linear_p95(FIRST_AUDIO_MS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
