// 問題1の解答：AAA パターンで支払総額のテストを書く。
import { describe, expect, it } from 'vitest';
import { buildPaymentSummary, calcSubtotal, resolveDiscountRule } from '../../session16/pricing';
import { soapCart } from '../test-data';

describe('buildPaymentSummary（石けん3点のカート）', () => {
  it('小計は1440円になる', () => {
    // Arrange
    const lines = soapCart;

    // Act
    const subtotal = calcSubtotal(lines);

    // Assert
    expect(subtotal).toBe(480 * 3);
  });

  it('会員ランクなしなら送料500円がかかり、支払総額は2084円になる', () => {
    // Arrange
    const rule = resolveDiscountRule('none');

    // Act
    const summary = buildPaymentSummary(soapCart, rule);

    // Assert
    expect(summary).toEqual({
      subtotal: 1440,
      discountAmount: 0,
      discountedTotal: 1440,
      tax: 144,
      totalWithTax: 1584,
      shippingFee: 500,
      payableAmount: 2084,
    });
  });

  it('ブロンズ会員は3%引きになり、支払総額は2036円になる', () => {
    const summary = buildPaymentSummary(soapCart, resolveDiscountRule('bronze'));

    expect(summary.discountAmount).toBe(43);
    expect(summary.discountedTotal).toBe(1397);
    expect(summary.tax).toBe(139);
    expect(summary.totalWithTax).toBe(1536);
    expect(summary.payableAmount).toBe(2036);
  });
});
