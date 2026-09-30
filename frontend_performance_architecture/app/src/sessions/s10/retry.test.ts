import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, createFakeApi } from './fakeApi';
import { TimeoutError, backoffDelay, isRetryable, withRetry } from './retry';

describe('backoffDelay（指数バックオフ）', () => {
  it('200 → 400 → 800 と倍々になり、上限で頭打ちになる', () => {
    expect([0, 1, 2].map((i) => backoffDelay(i, 200))).toEqual([200, 400, 800]);
    expect(backoffDelay(10, 200)).toBe(10_000);
  });
});

describe('isRetryable（待てば直る失敗か）', () => {
  const abort = new DOMException('中断しました', 'AbortError');
  const cases: [string, unknown, boolean][] = [
    ['503', new ApiError(503, ''), true],
    ['429', new ApiError(429, ''), true],
    ['408', new ApiError(408, ''), true],
    ['400', new ApiError(400, ''), false],
    ['404', new ApiError(404, ''), false],
    ['時間切れ', new TimeoutError(100), true],
    ['中断', abort, false],
  ];
  it.each(cases)('%s → %s', (_, error, expected) => {
    expect(isRetryable(error)).toBe(expected);
  });
});

describe('withRetry', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('冪等な読み取りは、失敗しても間隔を倍にしながらやり直す', async () => {
    const api = createFakeApi({ failOn: { firstCalls: 2 }, now: () => Date.now() });
    const delays: number[] = [];
    const promise = withRetry((signal) => api.getCategories(signal), {
      retries: 3,
      baseDelayMs: 200,
      timeoutMs: 1_000,
      idempotent: true,
      onRetry: (_, delayMs) => delays.push(delayMs),
    });
    await vi.advanceTimersByTimeAsync(1_500); // 300 失敗 → 200 待ち → 300 失敗 → 400 待ち → 300 成功
    await expect(promise).resolves.toEqual(['文具', '書籍', '雑貨', '食品']);
    expect(delays).toEqual([200, 400]);
    expect(api.calls.map((c) => c.outcome)).toEqual(['error', 'error', 'ok']);
    expect(api.calls[2]?.endedAt).toBe(1_500);
  });

  it('冪等でない書き込みは、失敗してもやり直さない', async () => {
    const api = createFakeApi({ failOn: { firstCalls: 1 }, now: () => Date.now() });
    const result = withRetry((signal) => api.setFavorite(1, true, signal), {
      retries: 3,
      baseDelayMs: 200,
      timeoutMs: 2_000,
      idempotent: false,
    }).catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(5_000);
    expect(await result).toBeInstanceOf(ApiError);
    expect(api.calls).toHaveLength(1);
  });

  it('制限時間を過ぎた試行は中断され、TimeoutError になる', async () => {
    const api = createFakeApi({ latencyMs: 300, now: () => Date.now() });
    const result = withRetry((signal) => api.getCategories(signal), {
      retries: 1,
      baseDelayMs: 200,
      timeoutMs: 100,
      idempotent: true,
    }).catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(await result).toBeInstanceOf(TimeoutError);
    expect(api.calls.map((c) => c.endedAt)).toEqual([100, 400]); // 100 で打ち切り → 200 待ち → 400 で打ち切り
  });

  it('呼び出し元が中断したら、リトライせずに終わる', async () => {
    const api = createFakeApi({ failOn: { firstCalls: 5 }, now: () => Date.now() });
    const controller = new AbortController();
    const result = withRetry((signal) => api.getCategories(signal), {
      retries: 3,
      baseDelayMs: 200,
      timeoutMs: 1_000,
      idempotent: true,
      signal: controller.signal,
    }).catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(100);
    controller.abort();
    await vi.advanceTimersByTimeAsync(5_000);
    expect((await result) as Error).toHaveProperty('name', 'AbortError');
    expect(api.calls).toHaveLength(1);
  });
});
