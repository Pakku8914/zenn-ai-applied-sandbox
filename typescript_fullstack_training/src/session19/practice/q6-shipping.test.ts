// 問題6の解答：しきい値ちょうどを足すとバグが見える。
import { describe, expect, it } from 'vitest';
import {
  calcRemainingForFreeShipping,
  isFreeShipping,
  isFreeShippingBuggy,
} from './q6-shipping';

describe('しきい値から離れた値だけでは差が出ない', () => {
  const cases: { totalWithTax: number; expected: boolean }[] = [
    { totalWithTax: 2000, expected: false },
    { totalWithTax: 5000, expected: true },
  ];

  it.each(cases)('税込 $totalWithTax 円 → $expected（両方の実装が同じ答え）', ({
    totalWithTax,
    expected,
  }) => {
    expect(isFreeShipping(totalWithTax)).toBe(expected);
    expect(isFreeShippingBuggy(totalWithTax)).toBe(expected);
  });
});

describe('しきい値ちょうどでバグが露見する', () => {
  it('3000円ちょうどは無料（バグ入りの実装は有料と判定してしまう）', () => {
    expect(isFreeShipping(3000)).toBe(true);
    expect(isFreeShippingBuggy(3000)).toBe(false);
  });

  it('2999円と3001円は両方の実装で一致する', () => {
    expect(isFreeShipping(2999)).toBe(false);
    expect(isFreeShippingBuggy(2999)).toBe(false);
    expect(isFreeShipping(3001)).toBe(true);
    expect(isFreeShippingBuggy(3001)).toBe(true);
  });
});

describe('calcRemainingForFreeShipping', () => {
  const cases: { totalWithTax: number; expected: number }[] = [
    { totalWithTax: 0, expected: 3000 },
    { totalWithTax: 2999, expected: 1 },
    { totalWithTax: 3000, expected: 0 },
    { totalWithTax: 4000, expected: 0 },
  ];

  it.each(cases)('税込 $totalWithTax 円 → あと $expected 円', ({ totalWithTax, expected }) => {
    expect(calcRemainingForFreeShipping(totalWithTax)).toBe(expected);
  });
});
