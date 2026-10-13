"""問題5：ウォームアップの失敗を、決めた回数だけ間を空けて再試行する。

    docker compose exec api python -m src.session14.solutions.q5_warm_retry
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx2

from src.session14.warmup import Warmer, Warmup

ATTEMPTS = 3
DELAY_SECONDS = 2.0


def retrying(warm: Warmer, *, attempts: int = ATTEMPTS, delay: float = DELAY_SECONDS,
             sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> Warmer:
    """接続の失敗（httpx2.HTTPError）だけを再試行する。それ以外の失敗は直らないので、すぐに諦める。"""
    async def run() -> None:
        for attempt in range(1, attempts + 1):
            try:
                await warm()
                return
            except httpx2.HTTPError:
                if attempt == attempts:
                    raise
                await sleep(delay)   # 待ち方を差し替えられるようにしておく（検証で本当に待たない）
    return run


class Flaky:
    """最初の fail_times 回だけ失敗する VOICEVOX の代役。"""

    def __init__(self, fail_times: int, error: type[Exception] = httpx2.ConnectError) -> None:
        self.fail_times, self.error, self.calls = fail_times, error, 0

    async def __call__(self) -> None:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.error("VOICEVOX ENGINE に接続できません")


async def trial(fail_times: int, error: type[Exception] = httpx2.ConnectError) -> tuple[dict, int, list[float]]:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    flaky = Flaky(fail_times, error)
    warmup = Warmup({"voicevox": retrying(flaky, sleep=fake_sleep)})
    warmup.start()
    await warmup.wait()
    return warmup.state, flaky.calls, slept


def run() -> list[str]:
    lines = []
    for label, fails, err in (("2回失敗して3回目で成功", 2, httpx2.ConnectError),
                              ("3回とも失敗", 3, httpx2.ConnectError),
                              ("接続以外の失敗（RuntimeError）", 1, RuntimeError)):
        state, calls, slept = asyncio.run(trial(fails, err))
        lines.append(f"{label}：state={state}・呼び出し {calls} 回・待った秒数 {slept}")
    return lines


def main() -> None:
    print("\n".join(run()))


if __name__ == "__main__":
    main()
