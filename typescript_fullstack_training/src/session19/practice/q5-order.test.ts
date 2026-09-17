// 問題5の解答：vi.fn で「通知が呼ばれたか」を検証する。
import { describe, expect, it, vi } from 'vitest';
import type { Notifier } from '../report';
import { requireProduct, toteBagCart } from '../test-data';
import { placeOrder } from './q5-order';

describe('placeOrder', () => {
  it('成功したら支払総額を添えて1回だけ通知する', () => {
    // Arrange
    const notify = vi.fn<Notifier>();

    // Act
    const result = placeOrder(toteBagCart, 'none', notify);

    // Assert
    expect(result.kind).toBe('ok');
    if (result.kind === 'ok') {
      expect(result.summary.payableAmount).toBe(3080);
    }
    expect(notify).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith('注文を受け付けました（3080円）');
  });

  it('カートが空なら失敗し、通知は送られない', () => {
    const notify = vi.fn<Notifier>();

    const result = placeOrder([], 'gold', notify);

    expect(result).toEqual({ kind: 'error', message: 'カートが空です' });
    expect(notify).not.toHaveBeenCalled();
  });

  it('数量が上限を超えていたら失敗し、通知は送られない', () => {
    const notify = vi.fn<Notifier>();

    const result = placeOrder([{ product: requireProduct(1), quantity: 11 }], 'none', notify);

    expect(result).toEqual({
      kind: 'error',
      message: '数量が上限を超えています: ラベンダーの石けん',
    });
    expect(notify).not.toHaveBeenCalled();
  });

  it('vi.fn を使わず、自分で書いた関数を渡してもテストできる', () => {
    const calls: string[] = [];
    const notify: Notifier = (message) => {
      calls.push(message);
    };

    placeOrder(toteBagCart, 'gold', notify);

    // ゴールド会員は10%引き。割引で税込が3000円を割るため送料500円がかかり、
    // 割引なし（3080円）より支払総額が高くなる（仕様として要注意な組み合わせ）
    expect(calls).toEqual(['注文を受け付けました（3272円）']);
  });
});
