// 金額計算。requirements.md の「支払総額の計算手順」をそのまま実装する。
import {
  DISCOUNT_PERCENT_BY_RANK,
  FREE_SHIPPING_THRESHOLD,
  SHIPPING_FEE,
  TAX_RATE,
} from './constants';
import type { CartLine, DiscountRule, MemberRank, PaymentSummary } from './types';

/** 小計（税抜・整数円） */
export function calcSubtotal(lines: readonly CartLine[]): number {
  return lines.reduce((total, line) => total + line.product.price * line.quantity, 0);
}

export function calcDiscountAmount(subtotal: number, percent: number): number {
  return Math.floor((subtotal * percent) / 100);
}

export function calcTax(discountedTotal: number, rate = TAX_RATE): number {
  return Math.floor(discountedTotal * rate);
}

/** 送料。判定基準は税込商品合計 */
export function calcShippingFee(totalWithTax: number): number {
  return totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
}

/** 会員ランクから割引ルール（関数）を作る */
export function resolveDiscountRule(rank: MemberRank): DiscountRule {
  const percent = DISCOUNT_PERCENT_BY_RANK[rank];
  return (subtotal) => calcDiscountAmount(subtotal, percent);
}

/** 支払総額の内訳を計算手順どおりに組み立てる */
export function buildPaymentSummary(
  lines: readonly CartLine[],
  rule: DiscountRule
): PaymentSummary {
  const subtotal = calcSubtotal(lines);
  const discountAmount = Math.min(rule(subtotal), subtotal);
  const discountedTotal = subtotal - discountAmount;
  const tax = calcTax(discountedTotal);
  const totalWithTax = discountedTotal + tax;
  const shippingFee = calcShippingFee(totalWithTax);

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
