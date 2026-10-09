"""練習問題6の解答：先頭の min_chars 文字まで貯めてから送り始め、貯めている間の失敗は再試行・フォールバックする。

「最初の差分を送る前なら再試行できる」の「前」を、TTFT と引き換えに少し後ろへずらす。
送り始めたあとは Session 6 と同じく error イベントで終える。
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

from .fallback import ResilientLLM, Served
from .providers import ChatRequest, Done, LLMProvider, ProviderError, StreamEvent, TextDelta
from .relay import Primed, close_upstream


async def _chain(held: list[StreamEvent], rest: AsyncIterator[StreamEvent], finished: bool) -> AsyncIterator[StreamEvent]:
    """貯めた分を先に流し、続きを上流から読む。閉じられたら上流も閉じる（aclose は内側へ伝わらないため）。"""
    try:
        for ev in held[1:]:
            yield ev
        if not finished:
            async for ev in rest:
                yield ev
    finally:
        await close_upstream(rest)


async def prime_buffered(provider: LLMProvider, chat: ChatRequest, min_chars: int) -> Primed:
    """テキストが min_chars 文字たまるか、Done が来るまで読む。ここで起きた失敗は ProviderError のまま上がる。"""
    if min_chars < 1:
        raise ValueError("min_chars は1以上にしてください")
    started = time.perf_counter()
    upstream = provider.stream(chat)
    held: list[StreamEvent] = []
    chars, finished = 0, False
    try:
        while chars < min_chars:
            try:
                ev = await anext(upstream)
            except StopAsyncIteration:
                finished = True
                break
            held.append(ev)
            if isinstance(ev, TextDelta):
                chars += len(ev.text)
            elif isinstance(ev, Done):
                finished = True
                break
    except BaseException:
        await close_upstream(upstream)
        raise
    if not held:
        raise ProviderError("bad_response", provider=provider.name)
    return Primed(chat, _chain(held, upstream, finished), held[0], started)


async def buffered_prime(llm: ResilientLLM, chat: ChatRequest, min_chars: int = 18) -> Served[Primed]:
    """ResilientLLM の経路・リトライ・ブレーカ・締め切りを、そのまま「貯める先読み」に使う。"""
    return await llm.run(chat, lambda provider, req: prime_buffered(provider, req, min_chars))
