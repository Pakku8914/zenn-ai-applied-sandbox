"""readiness（/ready）の判定。liveness（/health）は依存先を見ないので、ここには無い。

確認は並行に走らせ、1つあたり timeout 秒で打ち切る（遅い依存先1つのせいで /ready 自体が固まらないように）。
結果は "ok" / "ng" / "timeout" だけを返す。例外の文（接続文字列や内部のホスト名を含みうる）は返さない。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx2
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from .config import ProdSettings

logger = logging.getLogger("kondate.session16.probes")

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
        except Exception as exc:  # 種類を問わず「届かない」。中身はログに種類だけ残す
            status, exc_type = "ng", type(exc).__name__
        logger.warning("ready_check_failed", extra={"check": name, "status": status, "exc_type": exc_type})
        return name, status

    async def run(self) -> dict[str, str]:
        results = await asyncio.gather(*(self._one(name, fn) for name, fn in self.checks.items()))
        return dict(results)


def build_checks(settings: ProdSettings, engine: AsyncEngine, redis: Redis,
                 http: httpx2.AsyncClient) -> dict[str, CheckFn]:
    """このプロセスが要求を処理するのに欠かせない依存先だけを並べる。"""

    async def postgres() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def redis_ping() -> None:
        await redis.ping()

    checks: dict[str, CheckFn] = {"postgres": postgres, "redis": redis_ping}
    if settings.upstream_is_mock:
        # 上流が mockllm のときだけ見る。本物の LLM API は readiness で叩かない（課金・上流の障害で全台が外れる）
        async def mockllm() -> None:
            (await http.get(f"{settings.anthropic_base_url}/_mock/health")).raise_for_status()

        checks["mockllm"] = mockllm
    return checks
