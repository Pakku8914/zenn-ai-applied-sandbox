// 非同期処理のテスト。本文4節に対応する。
import { describe, expect, it, vi } from 'vitest';
import {
  createFlakyTask,
  delay,
  delayWithSignal,
  isAbortLike,
  retryWithBackoff,
  withTimeout,
} from '../session17/async-tools';
import { loadProducts, reserveStockStub } from '../session17/catalog';
import type { CatalogItem } from '../session17/catalog';
import { loadCatalogSafely } from '../session18/shop';
import { requireById } from './test-data';

/** retryWithBackoff に渡す通知関数の型（セッション17の onRetry と同じ形） */
type OnRetry = (attempt: number, waitMs: number, error: unknown) => void;

describe('await で結果を受け取ってから検証する', () => {
  it('fixtures から商品を5件読み込む', async () => {
    const products = await loadProducts();

    expect(products).toHaveLength(5);
    expect(requireById(products, 4, '商品').stock).toBe(0);
  });
});

describe('resolves / rejects で Promise のまま検証する', () => {
  it('resolves：在庫がある商品は確保できる', async () => {
    const products = await loadProducts();
    const mug = requireById(products, 3, '商品');

    await expect(reserveStockStub(mug)).resolves.toBe('確保しました（3点）');
  });

  it('rejects：在庫0の商品は確保に失敗する', async () => {
    const products = await loadProducts();
    const linen = requireById(products, 4, '商品');

    await expect(reserveStockStub(linen)).rejects.toThrow('在庫がありません');
  });
});

describe('withTimeout', () => {
  const fastTask = async (signal: AbortSignal): Promise<string> => {
    await delayWithSignal(5, signal);
    return '完了';
  };

  const slowTask = async (signal: AbortSignal): Promise<string> => {
    await delayWithSignal(200, signal);
    return '完了';
  };

  it('制限時間内に終われば結果を返す', async () => {
    await expect(withTimeout(fastTask, 100)).resolves.toBe('完了');
  });

  it('制限時間を超えたら中断エラーになる', async () => {
    let caught: unknown;

    try {
      await withTimeout(slowTask, 10);
    } catch (error) {
      caught = error;
    }

    // 中断のエラーは Error ではなく DOMException で届くことがあるため name で判定する
    expect(isAbortLike(caught)).toBe(true);
  });
});

describe('retryWithBackoff', () => {
  it('2回失敗して3回目で成功し、onRetry が2回呼ばれる', async () => {
    const task = createFlakyTask(2);
    const onRetry = vi.fn<OnRetry>();

    // baseMs を 1 にしておくと、待ち時間の合計は 1 + 2 = 3ms で済む
    const message = await retryWithBackoff(task, { retries: 3, baseMs: 1 }, onRetry);

    expect(message).toBe('成功（3回目で成功）');
    expect(onRetry).toHaveBeenCalledTimes(2);
    // 2番目の引数（待ち時間）が2倍ずつ増えていることを確かめる
    expect(onRetry.mock.calls.map((call) => call[1])).toEqual([1, 2]);
  });

  it('回数を使い切ったら最後のエラーを投げる', async () => {
    const task = createFlakyTask(10);

    await expect(retryWithBackoff(task, { retries: 2, baseMs: 1 })).rejects.toThrow(
      '一時的な失敗（3回目）'
    );
  });
});

describe('loadCatalogSafely（依存を引数で受け取るとモックが要らない）', () => {
  it('読み込みが成功すればカタログを返す', async () => {
    const result = await loadCatalogSafely();

    expect(result.kind).toBe('ok');
    if (result.kind === 'ok') {
      expect(result.value).toHaveLength(5);
    }
  });

  it('loader が例外を投げても Result の失敗になる', async () => {
    // 読み込みに失敗する状況を、引数を差し替えるだけで作れる
    const loader = vi.fn(async (): Promise<CatalogItem[]> => {
      throw new Error('ネットワークに接続できません');
    });

    const result = await loadCatalogSafely(loader);

    expect(loader).toHaveBeenCalledTimes(1);
    expect(result).toEqual({
      kind: 'error',
      error: { kind: 'catalog_unavailable', reason: 'ネットワークに接続できません' },
    });
  });
});

describe('fake timers（発展）', () => {
  it('待ち時間を手で進めれば、長い待機も一瞬で検証できる', async () => {
    vi.useFakeTimers();

    try {
      let finished = false;
      const waiting = delay(1000).then(() => {
        finished = true;
      });

      // 時間を進めていないので、まだ終わっていない
      expect(finished).toBe(false);

      await vi.advanceTimersByTimeAsync(1000);
      await waiting;

      expect(finished).toBe(true);
    } finally {
      // 必ず本物のタイマーに戻す。戻し忘れると後続のテストが固まる
      vi.useRealTimers();
    }
  });
});
