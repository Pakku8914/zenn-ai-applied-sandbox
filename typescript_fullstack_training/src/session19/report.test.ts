// モック関数（vi.fn）と「依存を引数で受け取る設計」のテスト。本文6節に対応する。
import { describe, expect, it, vi } from 'vitest';
import { products } from '../session16/shop-data';
import { buildStockReportLine, notifyLowStock } from './report';
import type { Notifier } from './report';
import { requireProduct } from './test-data';

describe('notifyLowStock', () => {
  it('在庫がしきい値以下の商品だけを通知する', () => {
    // Arrange: 本物の通知の代わりに「呼ばれたことを覚えるだけの関数」を渡す
    const notify = vi.fn<Notifier>();

    // Act
    const count = notifyLowStock(products, 3, notify);

    // Assert: 戻り値と「どう呼ばれたか」の両方を確かめる
    expect(count).toBe(2);
    expect(notify).toHaveBeenCalledTimes(2);
    expect(notify).toHaveBeenNthCalledWith(1, 'マグカップの在庫が残り3点です');
    expect(notify).toHaveBeenNthCalledWith(2, 'リネンのふきんの在庫が残り0点です');
  });

  it('該当する商品が無ければ1回も呼ばれない', () => {
    const notify = vi.fn<Notifier>();

    expect(notifyLowStock(products, -1, notify)).toBe(0);
    expect(notify).not.toHaveBeenCalled();
  });

  it('mock.calls で引数の一覧をまとめて確かめられる', () => {
    const notify = vi.fn<Notifier>();
    notifyLowStock(products, 0, notify);

    expect(notify.mock.calls).toEqual([['リネンのふきんの在庫が残り0点です']]);
  });
});

describe('buildStockReportLine', () => {
  it('現在時刻を引数で受け取るので、いつ実行しても結果が同じになる', () => {
    const now = new Date('2026-08-27T09:00:00Z');

    expect(buildStockReportLine(requireProduct(3), now)).toBe('[2026-08-27] マグカップ: 在庫3点');
  });
});
