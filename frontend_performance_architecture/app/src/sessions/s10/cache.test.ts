import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createQueryCache, judgeFreshness, type Freshness } from './cache';

const policy = { staleMs: 1_000, expireMs: 5_000 };

describe('judgeFreshness（失効の判断）', () => {
  const cases: [number | undefined, number, Freshness][] = [
    [undefined, 0, 'missing'],
    [0, 999, 'fresh'],
    [0, 1_000, 'stale'],
    [0, 4_999, 'stale'],
    [0, 5_000, 'expired'],
  ];
  it.each(cases)('fetchedAt=%s now=%i → %s', (fetchedAt, now, expected) => {
    expect(judgeFreshness(fetchedAt, now, policy)).toBe(expected);
  });
});

describe('createQueryCache（取得・キャッシュ・再検証・失効）', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  /** 100ms 後に「キー@取得時刻」を返す取得。failFrom 回目以降は失敗する */
  function setup(failFrom = Infinity) {
    let count = 0;
    const fetcher = vi.fn(
      (key: string) =>
        new Promise<string>((resolve, reject) => {
          count += 1;
          const n = count;
          setTimeout(() => (n >= failFrom ? reject(new Error('失敗')) : resolve(`${key}@${Date.now()}`)), 100);
        }),
    );
    const cache = createQueryCache<string>({ ...policy, fetcher, now: () => Date.now() });
    return { cache, fetcher };
  }

  it('初回は loading、応答が届くと success になる', async () => {
    const { cache } = setup();
    cache.ensure('a');
    expect(cache.getState('a')).toEqual({ status: 'loading' });
    await vi.advanceTimersByTimeAsync(100);
    expect(cache.getState('a')).toEqual({ status: 'success', data: 'a@100', revalidating: false });
  });

  it('進行中の同じキーは1本にまとめる（重複排除）', async () => {
    const { cache, fetcher } = setup();
    cache.ensure('a');
    cache.ensure('a');
    cache.ensure('a');
    await vi.advanceTimersByTimeAsync(100);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('新鮮な間は取得しない', async () => {
    const { cache, fetcher } = setup();
    cache.ensure('a');
    await vi.advanceTimersByTimeAsync(100);
    await vi.advanceTimersByTimeAsync(500);
    cache.ensure('a');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('古くなったら、古いデータを見せたまま裏で再検証する', async () => {
    const { cache, fetcher } = setup();
    cache.ensure('a');
    await vi.advanceTimersByTimeAsync(100); // a@100 を取得（t=100）
    await vi.advanceTimersByTimeAsync(1_000); // t=1100：経過 1000ms で stale
    cache.ensure('a');
    expect(cache.getState('a')).toEqual({ status: 'success', data: 'a@100', revalidating: true });
    await vi.advanceTimersByTimeAsync(100);
    expect(cache.getState('a')).toEqual({ status: 'success', data: 'a@1200', revalidating: false });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('失効したら古いデータを見せず、読み込み中に戻して取り直す', async () => {
    const { cache } = setup();
    cache.ensure('a');
    await vi.advanceTimersByTimeAsync(100);
    await vi.advanceTimersByTimeAsync(5_000); // 経過 5000ms で expired
    cache.ensure('a');
    expect(cache.getState('a')).toEqual({ status: 'loading' });
  });

  it('裏での再検証が失敗しても、手元のデータは消さない', async () => {
    const { cache } = setup(2);
    cache.ensure('a');
    await vi.advanceTimersByTimeAsync(100);
    await vi.advanceTimersByTimeAsync(1_000);
    cache.ensure('a');
    await vi.advanceTimersByTimeAsync(100);
    expect(cache.getState('a')).toEqual({ status: 'success', data: 'a@100', revalidating: false });
  });

  it('データが無いまま失敗したら error になる', async () => {
    const { cache } = setup(1);
    cache.ensure('a');
    await vi.advanceTimersByTimeAsync(100);
    const state = cache.getState('a');
    expect(state.status).toBe('error');
  });

  it('状態が変わらない間は同じ参照を返す（useSyncExternalStore の前提）', async () => {
    const { cache } = setup();
    cache.ensure('a');
    await vi.advanceTimersByTimeAsync(100);
    expect(cache.getState('a')).toBe(cache.getState('a'));
  });
});
