"""問題5：フォールバックの経路を、録画再生で決定的に試す（セッション15 × セッション11）。

- record_fallback()：mockllm から録る。primary は x-mock-fault: 529 を付けた接続（毎回 529）、light は正常な接続
- replay_fallback()：同じ経路の組を、カセットの再生で組み立て直して回す（mockllm には接続しない）
どちらも時計は FixedClock、待ちは FakeSleep、乱数は 0.5 固定なので、待ち時間まで毎回同じになる。
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import aclosing
from dataclasses import dataclass, replace
from pathlib import Path

from redis.asyncio import Redis

from kondate.clock import FixedClock
from kondate.settings import get_settings

from .breaker import PREFIX
from .cassette import RecordingProvider, ReplayProvider
from .fallback import ResilientLLM, Route
from .providers import Done, LLMProvider, TextDelta, Usage, open_provider
from .relay import chat_for, with_first
from .retry import FakeSleep

PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"
PRIMARY_CASSETTE = "primary.jsonl"
LIGHT_CASSETTE = "light.jsonl"


def half() -> float:
    return 0.5  # フルジッタの乱数を固定する（待ち時間 = 天井 × 0.5）


def routes_for(primary: LLMProvider, light: LLMProvider) -> list[Route]:
    s = get_settings()
    return [Route("primary", primary, s.llm_model), Route("light", light, s.llm_model_light)]


@dataclass(frozen=True)
class FallbackRun:
    route: str
    fallback: str | None
    attempts: list[tuple[str, int, str, float]]  # (経路, 何回目, 結果, 前に待った秒)
    sleeps: list[float]
    deltas: int
    usage: Usage | None


async def run_once(routes: Sequence[Route], redis: Redis) -> FallbackRun:
    """先読み（リトライ・フォールバック込み）から、ストリームの最後までを1回回す。"""
    clock = FixedClock()
    sleep = FakeSleep(clock)
    llm = ResilientLLM(routes, redis=redis, clock=clock, sleep=sleep, rand=half, prefix=PREFIX)
    served = await llm.prime(chat_for(PROMPT))
    deltas, usage = 0, None
    async with aclosing(with_first(served.value.first, served.value.upstream)) as events:
        async for ev in events:
            if isinstance(ev, TextDelta):
                deltas += 1
            elif isinstance(ev, Done):
                usage = ev.usage
    attempts = [(a.route, a.number, a.outcome, a.waited) for a in served.attempts]
    return FallbackRun(served.route, served.fallback, attempts, sleep.calls, deltas, usage)


async def record_fallback(directory: Path, redis: Redis) -> FallbackRun:
    """mockllm から録って、primary.jsonl と light.jsonl に保存する。"""
    s = get_settings()
    common = {"base_url": s.mockllm_url, "api_key": "mock-key", "max_retries": 0, "timeout": 30.0}
    async with open_provider("anthropic", model=s.llm_model, default_headers={"x-mock-fault": "529"},
                             **common) as broken, \
            open_provider("anthropic", model=s.llm_model_light, **common) as healthy:
        primary, light = RecordingProvider(broken), RecordingProvider(healthy)
        run = await run_once(routes_for(primary, light), redis)
    primary.save(directory / PRIMARY_CASSETTE)
    light.save(directory / LIGHT_CASSETTE)
    return run


async def replay_fallback(directory: Path, redis: Redis, *, light_model: str | None = None) -> FallbackRun:
    """カセットを再生して同じ経路の組を回し、録画を使い切ったことまで確かめる。"""
    primary = ReplayProvider.load(directory / PRIMARY_CASSETTE)
    light = ReplayProvider.load(directory / LIGHT_CASSETTE)
    routes = routes_for(primary, light)
    if light_model is not None:  # 経路のモデルを変えた（＝録画と違う要求を送る）場合を試す
        routes[1] = replace(routes[1], model=light_model)
    run = await run_once(routes, redis)
    primary.assert_all_used()
    light.assert_all_used()
    return run


def replay_routes(directory: Path) -> list[Route]:
    """問題7：アプリの get_llm に渡す経路（再生）。"""
    return routes_for(ReplayProvider.load(directory / PRIMARY_CASSETTE),
                      ReplayProvider.load(directory / LIGHT_CASSETTE))
