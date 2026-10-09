"""練習問題2：5つの状況で /health と /ready が何を返すかを、本物のアプリで確かめる。

    docker compose exec api python -m src.session16.q2_probe_cases
"""

from __future__ import annotations

import asyncio

from .app import create_app
from .harness import lab_settings, quiet, running

CASES = ("すべて正常", "Redis が応答しない", "mockllm が 5 秒黙る", "drain 中", "drain 中で Redis も応答しない")


async def broken() -> None:
    raise ConnectionError("接続できません")


async def silent() -> None:
    await asyncio.sleep(5)


async def observe(case: str) -> tuple[int, int, str]:
    """(/health のステータス, /ready のステータス, /ready の status) を返す。"""
    app = create_app(lab_settings(), configure_logging=False)
    async with running(app) as c:
        if "Redis" in case:
            app.state.probe.checks["redis"] = broken
        if "mockllm" in case:
            app.state.probe.checks["mockllm"] = silent
        if case.startswith("drain"):
            app.state.drain.begin()
        h, r = await c.get("/health"), await c.get("/ready")
    return h.status_code, r.status_code, r.json()["status"]


async def run_cases() -> dict[str, tuple[int, int, str]]:
    return {case: await observe(case) for case in CASES}


if __name__ == "__main__":
    quiet()
    for case, (health, ready, status) in asyncio.run(run_cases()).items():
        print(f"{case}: /health {health}・/ready {ready} {status}")
