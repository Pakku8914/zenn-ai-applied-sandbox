import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createFakeApi, isAbortError, searchLatency } from './fakeApi';
import { createLatestOnly } from './latest';
import { describeState, type RequestState } from './requestState';

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
});
afterEach(() => {
  vi.useRealTimers();
});

// 利用者が 60ms おきに「商」「商品」「商品1」と入力した状況
const typed = [
  { at: 0, keyword: '商' },
  { at: 60, keyword: '商品' },
  { at: 120, keyword: '商品1' },
];

describe('擬似 API の遅延は決定的', () => {
  it('キーワードが短いほど応答が遅い', () => {
    expect(['', '商', '商品', '商品1'].map(searchLatency)).toEqual([900, 700, 500, 300]);
  });
});

describe('競合状態', () => {
  it('Bad：届いた順に書くと、最後に残るのは最初に送った「商」の結果', async () => {
    const api = createFakeApi({ now: () => Date.now() });
    let shown = '';
    for (const { at, keyword } of typed) {
      setTimeout(() => {
        api.searchProducts(keyword).then(() => {
          shown = keyword;
        });
      }, at);
    }
    await vi.advanceTimersByTimeAsync(1_000);
    expect(shown).toBe('商');
  });

  it('リクエスト ID：最新でない応答は捨てる', async () => {
    const api = createFakeApi({ now: () => Date.now() });
    const latest = createLatestOnly();
    const applied: string[] = [];
    for (const { at, keyword } of typed) {
      setTimeout(() => {
        const isLatest = latest.begin();
        api.searchProducts(keyword).then(() => {
          if (isLatest()) applied.push(keyword);
        });
      }, at);
    }
    await vi.advanceTimersByTimeAsync(1_000);
    expect(applied).toEqual(['商品1']);
    expect(api.calls.map((c) => c.outcome)).toEqual(['ok', 'ok', 'ok']); // 通信は3本とも最後まで走る
  });

  it('AbortController：前の取得を中断すると、通信そのものが止まる', async () => {
    const api = createFakeApi({ now: () => Date.now() });
    let controller: AbortController | undefined;
    const applied: string[] = [];
    for (const { at, keyword } of typed) {
      setTimeout(() => {
        controller?.abort();
        controller = new AbortController();
        api.searchProducts(keyword, controller.signal).then(
          () => applied.push(keyword),
          (error: unknown) => {
            if (!isAbortError(error)) throw error;
          },
        );
      }, at);
    }
    await vi.advanceTimersByTimeAsync(1_000);
    expect(applied).toEqual(['商品1']);
    expect(api.calls.map((c) => c.outcome)).toEqual(['aborted', 'aborted', 'ok']);
  });
});

describe('describeState（判別可能ユニオン）', () => {
  const count = (items: readonly number[]) => items.length;
  const cases: [RequestState<number[]>, string][] = [
    [{ status: 'idle' }, 'キーワードを入力してください'],
    [{ status: 'loading' }, '読み込み中…'],
    [{ status: 'success', data: [1, 2, 3] }, '3 件'],
    [{ status: 'error', error: new Error('503') }, '読み込めませんでした（503）'],
  ];
  it.each(cases)('%o → %s', (state, expected) => {
    expect(describeState(state, count)).toBe(expected);
  });
});
