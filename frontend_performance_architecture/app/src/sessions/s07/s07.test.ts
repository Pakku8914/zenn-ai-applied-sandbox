import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildPointsChunked } from './buildPointsChunked';
import { ROWS, buildPointsSync } from './points';
import { debounce, throttle } from './rateLimit';
import { yieldStrategy, yieldToMain } from './yieldToMain';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('buildPointsChunked', () => {
  const expected = buildPointsSync();

  it('分割しても点列は同期版と完全に一致する（既定の予算）', async () => {
    const { points } = await buildPointsChunked();
    expect(points).toEqual(expected);
  });

  it('予算 0ms なら 1 点ごとに譲る（100 スライス）', async () => {
    const { points, chunks } = await buildPointsChunked({ budgetMs: 0 });
    expect(points).toEqual(expected);
    expect(chunks).toBe(ROWS);
  });

  it('予算が無限なら一度も譲らない（1 スライス）', async () => {
    const { chunks } = await buildPointsChunked({ budgetMs: Number.POSITIVE_INFINITY });
    expect(chunks).toBe(1);
  });

  it('途中で中断すると AbortError で止まり、続きを計算しない', async () => {
    const controller = new AbortController();
    let progressCalls = 0;
    const run = buildPointsChunked({
      budgetMs: 0,
      signal: controller.signal,
      onProgress: () => {
        progressCalls += 1;
        controller.abort();
      },
    });
    const reason = await run.then(
      () => null,
      (e: unknown) => e,
    );
    expect(reason instanceof Error || reason instanceof DOMException ? reason.name : reason).toBe('AbortError');
    expect(progressCalls).toBe(1);
  });
});

describe('yieldToMain', () => {
  it('Node には scheduler が無いので MessageChannel を使う', async () => {
    expect(yieldStrategy()).toBe('message-channel');
    await expect(yieldToMain()).resolves.toBeUndefined();
  });

  it('scheduler.yield があればそれを使う', async () => {
    const fakeYield = vi.fn(() => Promise.resolve());
    vi.stubGlobal('scheduler', { yield: fakeYield });
    expect(yieldStrategy()).toBe('scheduler.yield');
    await yieldToMain();
    expect(fakeYield).toHaveBeenCalledTimes(1);
  });

  it('MessageChannel も無ければ setTimeout に落とす', async () => {
    vi.stubGlobal('MessageChannel', undefined);
    expect(yieldStrategy()).toBe('set-timeout');
    await expect(yieldToMain()).resolves.toBeUndefined();
  });
});

describe('debounce と throttle', () => {
  it('debounce：50ms おきに 10 回呼ぶと、止まってから 200ms 後に最後の 1 回だけ実行する', () => {
    vi.useFakeTimers();
    const calls: number[] = [];
    const search = debounce((n: number) => calls.push(n), 200);
    for (let i = 0; i < 10; i += 1) {
      search(i);
      vi.advanceTimersByTime(50);
    }
    expect(calls).toEqual([]);
    vi.advanceTimersByTime(200);
    expect(calls).toEqual([9]);
  });

  it('throttle：50ms おきに 20 回呼ぶと、200ms に 1 回ずつ実行する（先頭と末尾を含む）', () => {
    vi.useFakeTimers();
    const calls: number[] = [];
    const onScroll = throttle((n: number) => calls.push(n), 200);
    for (let i = 0; i < 20; i += 1) {
      onScroll(i);
      vi.advanceTimersByTime(50);
    }
    vi.advanceTimersByTime(1_000);
    expect(calls).toEqual([0, 3, 7, 11, 15, 19]);
  });

  it('cancel で予約済みの実行を取り消せる', () => {
    vi.useFakeTimers();
    const calls: number[] = [];
    const search = debounce((n: number) => calls.push(n), 200);
    search(1);
    search.cancel();
    vi.advanceTimersByTime(1_000);
    expect(calls).toEqual([]);
  });
});
