// 問題6：カバレッジ100%でもバグが残る例。
// 2つの実装は「しきい値ちょうど」のときだけ結果が違う。

import { FREE_SHIPPING_THRESHOLD } from '../../session16/constants';

/** バグ入り：>= ではなく > で書いているため、3000円ちょうどが無料にならない */
export function isFreeShippingBuggy(totalWithTax: number): boolean {
  return totalWithTax > FREE_SHIPPING_THRESHOLD;
}

/** 正しい実装：3000円ちょうどで無料になる */
export function isFreeShipping(totalWithTax: number): boolean {
  return totalWithTax >= FREE_SHIPPING_THRESHOLD;
}

/** 送料無料まであと何円か。すでに無料なら0 */
export function calcRemainingForFreeShipping(totalWithTax: number): number {
  return Math.max(FREE_SHIPPING_THRESHOLD - totalWithTax, 0);
}
