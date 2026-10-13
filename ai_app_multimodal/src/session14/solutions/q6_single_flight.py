"""問題6：同じキーの同時リクエストを、1回の LLM 呼び出しにまとめる（single-flight）。

    docker compose exec api python -m src.session14.solutions.q6_single_flight

応答キャッシュは「結果が入った後」の再送しか救えない。1回目の結果を待っている間に届いた同じ依頼は、
キャッシュがまだ空なので、そのままでは全員が LLM を呼んでしまう。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from kondate.clock import FixedClock
from kondate.llm import Usage
from src.session14.cache import ResponseCache


class SingleFlight:
    def __init__(self) -> None:
        self._running: dict[str, asyncio.Future] = {}
        self.shared = 0  # 相乗りした数（累計）

    async def do(self, key: str, fn: Callable[[], Awaitable[Any]]) -> tuple[Any, bool]:
        """(結果, 相乗りしたか) を返す。同じ key の計算が走っていれば、その結果を待つ。"""
        if (fut := self._running.get(key)) is not None:
            self.shared += 1
            return await asyncio.shield(fut), True   # 待っている側が取り消されても、計算は止めない
        fut = asyncio.get_running_loop().create_future()
        self._running[key] = fut
        try:
            result = await fn()
        except asyncio.CancelledError:
            fut.cancel()
            raise
        except Exception as e:
            fut.set_exception(e)
            fut.exception()                          # 相乗りがいなくても「未回収の例外」の警告を出さない
            raise
        else:
            fut.set_result(result)
            return result, False
        finally:
            del self._running[key]                   # 終わったら外す（失敗した結果を次の人に渡さない）


async def cached_call(cache: ResponseCache, flights: SingleFlight, key: str, scope: str,
                      compute: Callable[[], Awaitable[tuple[dict, Usage]]]) -> tuple[dict, str]:
    """応答キャッシュ → 相乗り → 計算 の順に試す。2つ目は "hit" / "shared" / "miss"。"""
    if (entry := cache.get(key)) is not None:
        return entry.value, "hit"

    async def fill() -> dict:
        value, usage = await compute()
        cache.put(key, scope, value, usage)          # 成功したときだけ入れる
        return value

    value, joined = await flights.do(key, fill)
    return value, "shared" if joined else "miss"


async def scenario() -> list[str]:
    cache, flights = ResponseCache(FixedClock()), SingleFlight()
    calls = 0
    release = asyncio.Event()

    async def compute() -> tuple[dict, Usage]:
        nonlocal calls
        calls += 1
        await release.wait()
        return {"ingredients": ["キャベツ"]}, Usage(1668, 194)

    async def until_shared(n: int) -> None:
        while flights.shared < n:
            await asyncio.sleep(0)

    tasks = [asyncio.create_task(cached_call(cache, flights, "k1", "u001", compute)) for _ in range(3)]
    await until_shared(2)
    release.set()
    results = await asyncio.gather(*tasks)
    kinds = sorted(k for _, k in results)
    same = all(v == results[0][0] for v, _ in results)
    lines = [f"同時に3件：計算 {calls} 回・{'／'.join(kinds)}・3件とも同じ結果={same}"]

    _, kind = await cached_call(cache, flights, "k1", "u001", compute)
    lines.append(f"後から1件：{kind}（計算は {calls} 回のまま）")

    broken = asyncio.Event()

    async def failing() -> tuple[dict, Usage]:
        nonlocal calls
        calls += 1
        await broken.wait()
        raise RuntimeError("読み取りに失敗しました")

    tasks = [asyncio.create_task(cached_call(cache, flights, "k2", "u001", failing)) for _ in range(2)]
    await until_shared(3)
    broken.set()
    errors = await asyncio.gather(*tasks, return_exceptions=True)
    names = [type(e).__name__ for e in errors]
    in_cache = cache.get("k2") is not None
    _, kind = await cached_call(cache, flights, "k2", "u001", compute)
    lines.append(f"失敗：同時の2件とも {'・'.join(names)}・キャッシュに残る={in_cache} → 次の1件は {kind}（計算は合計 {calls} 回）")
    return lines


def run() -> list[str]:
    return asyncio.run(scenario())


def main() -> None:
    print("\n".join(run()))


if __name__ == "__main__":
    main()
