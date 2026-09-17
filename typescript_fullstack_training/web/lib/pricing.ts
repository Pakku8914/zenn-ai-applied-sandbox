// 支払総額の内訳を計算する。手順と丸めは本書共通（セッション5で確定した1〜7）。
// 送料の判定に使うのは「税込商品合計」であって、税抜小計ではない。

import type { CartLine } from '@/lib/cart';

export const TAX_RATE = 0.1;
export const SHIPPING_FEE = 500;
export const FREE_SHIPPING_THRESHOLD = 3000;

/** 割引ルール。小計を受け取って割引額を返す関数（セッション6で決めた形） */
export type DiscountRule = (subtotal: number) => number;

/** 割引なし。会員ランクによる割引はのちの章で扱う */
export const noDiscount: DiscountRule = () => 0;

export type PaymentSummary = {
  subtotal: number;
  discountAmount: number;
  discountedTotal: number;
  tax: number;
  totalWithTax: number;
  shippingFee: number;
  payableAmount: number;
};

export function calcLineTotal(price: number, quantity: number): number {
  return price * quantity;
}

export function calcSubtotal(lines: readonly CartLine[]): number {
  return lines.reduce(
    (total, line) => total + calcLineTotal(line.product.price, line.quantity),
    0
  );
}

/** 送料。判定の基準は税込商品合計（手順5）である */
export function calcShippingFee(totalWithTax: number): number {
  return totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
}

/** 送料無料まであといくらか。すでに無料なら 0 */
export function calcRemainingForFreeShipping(totalWithTax: number): number {
  return Math.max(0, FREE_SHIPPING_THRESHOLD - totalWithTax);
}

/** 明細から支払総額の内訳を作る。丸めは消費税の計算時に一度だけ */
export function buildPaymentSummary(
  lines: readonly CartLine[],
  rule: DiscountRule = noDiscount
): PaymentSummary {
  const subtotal = calcSubtotal(lines);
  // 割引が小計を超えて金額がマイナスになると、税と送料の判定まで壊れる
  const discountAmount = Math.min(Math.floor(rule(subtotal)), subtotal);
  const discountedTotal = subtotal - discountAmount;
  const tax = Math.floor(discountedTotal * TAX_RATE);
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
