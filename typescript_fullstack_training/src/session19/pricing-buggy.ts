// わざとバグを入れた支払総額の計算。
// 送料の判定を「税込商品合計」ではなく「割引後小計（税抜）」で行っている。
// テストがこの間違いを捕まえられることを確かめるために置いてある。実装の手本ではない。

import { calcShippingFee, calcSubtotal, calcTax } from '../session16/pricing';
import type { CartLine, DiscountRule, PaymentSummary } from '../session16/types';

export function buildPaymentSummaryBuggy(
  lines: readonly CartLine[],
  rule: DiscountRule
): PaymentSummary {
  const subtotal = calcSubtotal(lines);
  const discountAmount = Math.min(rule(subtotal), subtotal);
  const discountedTotal = subtotal - discountAmount;
  const tax = calcTax(discountedTotal);
  const totalWithTax = discountedTotal + tax;

  // バグ：本来は totalWithTax（税込商品合計）で判定する
  const shippingFee = calcShippingFee(discountedTotal);

  return {
    subtotal,
    discountAmount,
    discountedTotal,
    tax,
    totalWithTax,
    shippingFee,
    payableAmount: totalWithTax + shippingFee,
  };
}
