// 問題3の解答：割引ルールの組み立て。土台とランク判定だけを見る（逆向きの矢印は無い）。
import { DISCOUNT_PERCENT_BY_RANK } from './q3-member';
import type { MemberRank } from './q3-member';
import { resolveMemberRank } from './q3-rank';

/** 小計を受け取って割引額を返す関数（セッション6で決めた形） */
export type DiscountRule = (subtotal: number) => number;

export function makePercentDiscount(percent: number): DiscountRule {
  return (subtotal) => Math.floor((subtotal * percent) / 100);
}

export function resolveDiscountRule(rank: MemberRank): DiscountRule {
  return makePercentDiscount(DISCOUNT_PERCENT_BY_RANK[rank]);
}

/** 累計購入額から一気に割引ルールを作る（呼ぶ側の手間を減らす入口） */
export function resolveRuleBySpent(totalSpent: number): DiscountRule {
  return resolveDiscountRule(resolveMemberRank(totalSpent));
}
