// 累計購入額から会員ランクを求める（しきい値はセッション3で決めた 50000 / 20000 / 5000）。
// 境界値テストの題材として、セッション19で単体のモジュールに切り出している。

import type { MemberRank } from '../session16/types';

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
