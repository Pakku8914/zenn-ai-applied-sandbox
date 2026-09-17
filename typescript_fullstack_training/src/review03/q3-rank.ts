// 問題3の解答：ランクの判定と表示。土台（q3-member）だけを見る。
import { DISCOUNT_PERCENT_BY_RANK } from './q3-member';
import type { MemberRank } from './q3-member';

/** 累計購入額から会員ランクを求める（しきい値は本書共通） */
export function resolveMemberRank(totalSpent: number): MemberRank {
  if (totalSpent >= 50000) {
    return 'gold';
  }
  if (totalSpent >= 20000) {
    return 'silver';
  }
  if (totalSpent >= 5000) {
    return 'bronze';
  }
  return 'none';
}

/** 表示用の文字列。定数は土台から読むので、割引モジュールを import しない */
export function describeRank(rank: MemberRank): string {
  return `${rank}（${DISCOUNT_PERCENT_BY_RANK[rank]}%割引）`;
}
