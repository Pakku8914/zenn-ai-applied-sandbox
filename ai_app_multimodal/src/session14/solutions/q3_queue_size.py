"""問題3：同時実行数と待ち行列の長さを決め、まとめて来たときに何件断るかを確かめる。

    docker compose exec api python -m src.session14.solutions.q3_queue_size
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from src.session14.gate import Busy, CpuGate

BUDGET = Decimal("5")  # 待ってよい時間（秒）


def service_seconds(audio_seconds: Decimal, rtf: Decimal) -> Decimal:
    """1件の処理時間＝音声の長さ×RTF。"""
    return audio_seconds * rtf


def max_waiting_for(budget: Decimal, service: Decimal, concurrency: int) -> int:
    """待ち行列の最後の人が待つ時間（＝前に並ぶ件数÷同時実行数×1件の処理時間）が budget に収まる長さ。"""
    return int(budget / service) * concurrency


def burst(n: int, concurrency: int, max_waiting: int) -> tuple[int, int]:
    accepted = min(n, concurrency + max_waiting)
    return accepted, n - accepted


async def burst_with_gate(n: int, concurrency: int, max_waiting: int) -> tuple[int, int]:
    """本物の CpuGate に n 件を同時に入れ、受け付けた数と断った数を数える（時間は使わない）。"""
    gate = CpuGate("q3", concurrency, max_waiting)
    release = asyncio.Event()

    async def work() -> None:
        await release.wait()

    tasks = [asyncio.create_task(gate.run(work)) for _ in range(n)]
    while gate.inflight + gate.rejected < n:   # 全員が入口に着くまで待つ
        await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    rejected = sum(isinstance(r, Busy) for r in results)
    return n - rejected, rejected


def run() -> list[str]:
    stt = service_seconds(Decimal("4.0"), Decimal("0.6"))   # 1発話 4 秒・RTF 0.6
    tts = service_seconds(Decimal("3.0"), Decimal("0.55"))  # 1文 3 秒・RTF 0.55
    lines = [
        f"STT：1件 {stt:.2f} 秒・待ってよい {BUDGET} 秒・同時 1 件 → 待ち行列 {max_waiting_for(BUDGET, stt, 1)} 件",
        f"TTS：1件 {tts:.2f} 秒・待ってよい {BUDGET} 秒・同時 1 件 → 待ち行列 {max_waiting_for(BUDGET, tts, 1)} 件",
        f"STT：1件 {stt:.2f} 秒・待ってよい {BUDGET} 秒・同時 2 件 → 待ち行列 {max_waiting_for(BUDGET, stt, 2)} 件",
    ]
    for c, w in ((1, 2), (2, 4)):
        a, r = burst(6, c, w)
        ga, gr = asyncio.run(burst_with_gate(6, c, w))
        lines.append(f"6件同時（同時 {c}・待ち {w}）：計算 受付 {a}・断る {r}／CpuGate 受付 {ga}・断る {gr}")
    return lines


def main() -> None:
    print("\n".join(run()))


if __name__ == "__main__":
    main()
