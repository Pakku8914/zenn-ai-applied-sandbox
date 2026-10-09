"""readiness（/ready）の判定（session16/probes.py のコピー）。結果は "ok" / "ng" / "timeout" だけを返す。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx2
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("kondate.final.probes")

CheckFn = Callable[[], Awaitable[object]]


class ReadinessProbe:
    def __init__(self, checks: dict[str, CheckFn], timeout: float) -> None:
        self.checks = dict(checks)
        self.timeout = timeout

    async def _one(self, name: str, fn: CheckFn) -> tuple[str, str]:
        try:
            async with asyncio.timeout(self.timeout):
                await fn()
            return name, "ok"
        except TimeoutError:
            status, exc_type = "timeout", "TimeoutError"
        except Exception as exc:
            status, exc_type = "ng", type(exc).__name__
        logger.warning("ready_check_failed", extra={"check": name, "status": status, "exc_type": exc_type})
        return name, status

    async def run(self) -> dict[str, str]:
        results = await asyncio.gather(*(self._one(name, fn) for name, fn in self.checks.items()))
        return dict(results)


def build_checks(engine: AsyncEngine, redis: Redis, http: httpx2.AsyncClient, *,
                 mock_url: str | None) -> dict[str, CheckFn]:
    """要求を処理するのに欠かせない依存先だけを並べる。mockllm は上流が mockllm のときだけ見る。"""

    async def postgres() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def redis_ping() -> None:
        await redis.ping()

    checks: dict[str, CheckFn] = {"postgres": postgres, "redis": redis_ping}
    if mock_url is not None:
        async def mockllm() -> None:
            (await http.get(f"{mock_url}/_mock/health")).raise_for_status()

        checks["mockllm"] = mockllm
    return checks
