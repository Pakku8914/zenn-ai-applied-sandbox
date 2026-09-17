// 支払総額の計算のテスト。本文1〜3節に対応する。
import { describe, expect, it } from 'vitest';
import { buildPaymentSummary, calcShippingFee, resolveDiscountRule } from '../session16/pricing';
import { buildPaymentSummaryBuggy } from './pricing-buggy';
import { mixedCart, toteBagCart } from './test-data';

describe('buildPaymentSummary', () => {
  it('トートバッグ1点（税抜2800円）は税込3080円で送料が無料になる', () => {
    // Arrange（準備）
    const lines = toteBagCart;
    const rule = resolveDiscountRule('none');

    // Act（実行）
    const summary = buildPaymentSummary(lines, rule);

    // Assert（検証）
    expect(summary.subtotal).toBe(2800);
    expect(summary.tax).toBe(280);
    expect(summary.totalWithTax).toBe(3080);
    expect(summary.shippingFee).toBe(0);
    expect(summary.payableAmount).toBe(3080);
  });

  it('ゴールド会員の内訳を丸ごと比べる', () => {
    const summary = buildPaymentSummary(mixedCart, resolveDiscountRule('gold'));

    expect(summary).toEqual({
      subtotal: 3310,
      discountAmount: 331,
      discountedTotal: 2979,
      tax: 297,
      totalWithTax: 3276,
      shippingFee: 0,
      payableAmount: 3276,
    });
  });

  it('空のカートはすべて0になる', () => {
    const summary = buildPaymentSummary([], resolveDiscountRule('none'));

    expect(summary.subtotal).toBe(0);
    expect(summary.totalWithTax).toBe(0);
    expect(summary.shippingFee).toBe(500); // 商品が1つも無いのに送料500円（仕様の穴）
    expect(summary.payableAmount).toBe(500);
  });
});

describe('calcShippingFee の境界（3000円ちょうど）', () => {
  const cases: { totalWithTax: number; expected: number }[] = [
    { totalWithTax: 0, expected: 500 },
    { totalWithTax: 2999, expected: 500 },
    { totalWithTax: 3000, expected: 0 },
    { totalWithTax: 3001, expected: 0 },
  ];

  it.each(cases)('税込 $totalWithTax 円 → 送料 $expected 円', ({ totalWithTax, expected }) => {
    expect(calcShippingFee(totalWithTax)).toBe(expected);
  });
});

describe('バグ入りの実装はテストが捕まえる', () => {
  it('送料を税抜で判定すると、無料のはずのカートに500円が付く', () => {
    const rule = resolveDiscountRule('none');
    const correct = buildPaymentSummary(toteBagCart, rule);
    const buggy = buildPaymentSummaryBuggy(toteBagCart, rule);

    expect(correct.shippingFee).toBe(0);
    expect(correct.payableAmount).toBe(3080);
    expect(buggy.shippingFee).toBe(500);
    expect(buggy.payableAmount).toBe(3580);
    expect(buggy.payableAmount).not.toBe(correct.payableAmount);
  });

  it('割引で税抜が3000円を割るカートでも差が出る', () => {
    const rule = resolveDiscountRule('gold');

    expect(buildPaymentSummary(mixedCart, rule).payableAmount).toBe(3276);
    expect(buildPaymentSummaryBuggy(mixedCart, rule).payableAmount).toBe(3776);
  });
});
