import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { products } from '../../../data/products';
import { ApiError, wait } from '../fakeApi';
import { TimeoutError } from '../retry';
import { loadDetailParallel, loadDetailSerial, type DetailApi } from './detail';
import { createInvalidatingCache } from './invalidatingCache';
import { createOptimisticCounter } from './optimisticCounter';
import { shouldRetry } from './retryDecision';
import { fromFlags, statusText } from './searchState';
import { SKIPPED, takeLatest } from './takeLatest';

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
});
afterEach(() => {
  vi.useRealTimers();
});

describe('問題2：判別可能ユニオン', () => {
  const items = products.slice(0, 3);
  it.each([
    [{ isLoading: false, error: null, data: null }, 'キーワードを入力してください'],
    [{ isLoading: true, error: null, data: null }, '読み込み中…'],
    [{ isLoading: true, error: null, data: items }, '3 件（更新を確認中）'],
    [{ isLoading: false, error: null, data: items }, '3 件'],
    [{ isLoading: false, error: new Error('503'), data: null }, '読み込めませんでした（503）'],
    [{ isLoading: true, error: new Error('503'), data: items }, '3 件（最新の取得に失敗しました）'],
  ])('%o → %s', (flags, expected) => {
    expect(statusText(fromFlags(flags))).toBe(expected);
  });
});

describe('問題3：takeLatest', () => {
  it('最後の呼び出しの結果だけを返し、それ以前は SKIPPED になる', async () => {
    const search = takeLatest(async (keyword: string) => {
      await wait(900 - keyword.length * 200);
      return keyword;
    });
    const results = Promise.all([search('商'), search('商品'), search('商品1')]);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(await results).toEqual([SKIPPED, SKIPPED, '商品1']);
  });

  it('古い呼び出しの失敗も SKIPPED にする（最新の画面にエラーを出さない）', async () => {
    const run = takeLatest(async (n: number) => {
      await wait(100);
      if (n === 1) throw new Error('古い失敗');
      return n;
    });
    const results = Promise.all([run(1), run(2)]);
    await vi.advanceTimersByTimeAsync(100);
    expect(await results).toEqual([SKIPPED, 2]);
  });
});

describe('問題4：楽観的なカウンター', () => {
  it('失敗した操作だけが外れ、後の操作は残る', () => {
    const counter = createOptimisticCounter(2);
    const a = counter.add(1);
    const b = counter.add(1);
    expect(counter.value()).toBe(4);
    counter.fail(a);
    expect(counter.value()).toBe(3);
    counter.confirm(b);
    expect(counter.value()).toBe(3);
    expect(counter.pendingCount()).toBe(0);
  });

  it('同じ操作を2回 confirm しても、値は1回しか増えない', () => {
    const counter = createOptimisticCounter(0);
    const a = counter.add(1);
    counter.confirm(a);
    counter.confirm(a);
    expect(counter.value()).toBe(1);
  });
});

describe('問題5：リトライするか', () => {
  const unavailable = new ApiError(503, '');
  it.each([
    ['GET が 503', { method: 'GET' } as const, unavailable, true],
    ['GET が 404', { method: 'GET' } as const, new ApiError(404, ''), false],
    ['PUT が時間切れ', { method: 'PUT' } as const, new TimeoutError(100), true],
    ['POST が 503', { method: 'POST' } as const, unavailable, false],
    ['冪等キー付き POST が 503', { method: 'POST', hasIdempotencyKey: true } as const, unavailable, true],
    ['冪等キー付き POST が 400', { method: 'POST', hasIdempotencyKey: true } as const, new ApiError(400, ''), false],
  ])('%s → %s', (_, op, error, expected) => {
    expect(shouldRetry(op, error)).toBe(expected);
  });
});

describe('問題6：ウォーターフォールの解消', () => {
  const api: DetailApi = {
    getProduct: async (id) => {
      await wait(300);
      return { id, name: `商品${id}`, category: '書籍' };
    },
    getReviews: async () => {
      await wait(400);
      return ['良い'];
    },
    getRelated: async (category) => {
      await wait(300);
      return [`${category}の人気商品`];
    },
  };

  it('直列は 300 + 400 + 300 = 1000ms', async () => {
    const done = loadDetailSerial(api, 5).then(() => Date.now());
    await vi.advanceTimersByTimeAsync(1_000);
    expect(await done).toBe(1_000);
  });

  it('依存のとおりに並べると max(300 + 300, 400) = 600ms（直列の 0.6 倍）', async () => {
    const done = loadDetailParallel(api, 5).then((detail) => ({ at: Date.now(), detail }));
    await vi.advanceTimersByTimeAsync(600);
    const { at, detail } = await done;
    expect(at).toBe(600);
    expect(detail.related).toEqual(['書籍の人気商品']);
  });
});

describe('問題7：変更後の無効化', () => {
  function setup() {
    let version = 1;
    const fetcher = vi.fn(async (key: string) => {
      const v = version;
      await wait(100);
      return `${key}@v${v}`;
    });
    const cache = createInvalidatingCache<string>({ fetcher, staleMs: 30_000, expireMs: 300_000, now: () => Date.now() });
    return { cache, fetcher, bump: () => (version += 1) };
  }

  it('無効化したキーは新鮮でも取り直す。古いデータは取り直すまで見せる', async () => {
    const { cache, fetcher, bump } = setup();
    cache.ensure('fav:1');
    cache.ensure('search:商品');
    await vi.advanceTimersByTimeAsync(100);
    bump(); // サーバー側でお気に入りが変わった
    expect(cache.invalidate((key) => key.startsWith('fav:'))).toBe(1);
    expect(cache.getState('fav:1')).toEqual({ status: 'success', data: 'fav:1@v1', revalidating: false });
    cache.ensure('fav:1');
    cache.ensure('search:商品'); // 無効化していないので取り直さない
    await vi.advanceTimersByTimeAsync(100);
    expect(cache.getState('fav:1')).toEqual({ status: 'success', data: 'fav:1@v2', revalidating: false });
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it('取得の途中で無効化されたら、届いた応答を新鮮扱いしない', async () => {
    const { cache, fetcher, bump } = setup();
    cache.ensure('fav:1'); // v1 を取りに行く
    bump();
    cache.invalidate((key) => key === 'fav:1'); // 変更前に始まった取得の途中で無効化
    await vi.advanceTimersByTimeAsync(100);
    cache.ensure('fav:1');
    await vi.advanceTimersByTimeAsync(100);
    expect(cache.getState('fav:1')).toEqual({ status: 'success', data: 'fav:1@v2', revalidating: false });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
