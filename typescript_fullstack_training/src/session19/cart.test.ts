// カートの変換と数量の上限のテスト。本文2〜3節に対応する。
import { describe, expect, it } from 'vitest';
import { describeLine, isWithinQuantityLimit, toCartLines } from '../session16/cart';
import { MAX_CART_QUANTITY } from '../session16/constants';
import { brokenCartItems, cartItems } from '../session16/shop-data';
import { requireProduct } from './test-data';

describe('toCartLines', () => {
  it('DB 行の形を計算用の形に変換する', () => {
    // Arrange / Act
    const lines = toCartLines(cartItems);

    // Assert
    expect(lines).toHaveLength(2);
    expect(lines.map((line) => line.product.name)).toEqual(['ラベンダーの石けん', 'マグカップ']);
    expect(lines.map((line) => line.quantity)).toEqual([2, 1]);
  });

  it('存在しない商品を指す明細は落とす', () => {
    const lines = toCartLines(brokenCartItems);

    expect(lines).toHaveLength(1);
    expect(lines.map((line) => line.product.id)).toEqual([1]);
  });

  it('空の配列を渡したら空の配列が返る', () => {
    expect(toCartLines([])).toEqual([]);
  });
});

describe('isWithinQuantityLimit の境界', () => {
  const cases: { quantity: number; expected: boolean }[] = [
    { quantity: 0, expected: false },
    { quantity: 1, expected: true },
    { quantity: MAX_CART_QUANTITY, expected: true },
    { quantity: MAX_CART_QUANTITY + 1, expected: false },
  ];

  it.each(cases)('数量 $quantity → $expected', ({ quantity, expected }) => {
    const line = { product: requireProduct(1), quantity };

    expect(isWithinQuantityLimit(line)).toBe(expected);
  });
});

describe('describeLine', () => {
  it('表示用の文字列を組み立てる', () => {
    expect(describeLine({ product: requireProduct(3), quantity: 2 })).toBe(
      'マグカップ × 2点 = 4700円'
    );
  });
});
