// 章をまたいで変わらない定数。型だけを import しているので import type を使う。
import type { MemberRank } from './types';

export const TAX_RATE = 0.1;
export const SHIPPING_FEE = 500;
export const FREE_SHIPPING_THRESHOLD = 3000;
/** 1明細に入れられる数量の上限 */
export const MAX_CART_QUANTITY = 10;

/**
 * 会員ランクごとの割引率（%）。
 * as const で値の型を 10 / 5 / 3 / 0 のまま保ち、
 * satisfies で「MemberRank のキーを網羅しているか」だけを検査させる。
 */
export const DISCOUNT_PERCENT_BY_RANK = {
  gold: 10,
  silver: 5,
  bronze: 3,
  none: 0,
} as const satisfies Record<MemberRank, number>;
