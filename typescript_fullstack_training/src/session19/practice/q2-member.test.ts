// 問題2の解答：会員ランクのしきい値を it.each（テーブル駆動）で網羅する。
import { describe, expect, it } from 'vitest';
import { resolveDiscountRule } from '../../session16/pricing';
import type { MemberRank } from '../../session16/types';
import { resolveMemberRank } from '../member';

describe('resolveMemberRank のしきい値', () => {
  // しきい値の「直前」「ちょうど」を必ずセットで並べる
  const cases: { totalSpent: number; expected: MemberRank }[] = [
    { totalSpent: 0, expected: 'none' },
    { totalSpent: 4999, expected: 'none' },
    { totalSpent: 5000, expected: 'bronze' },
    { totalSpent: 19999, expected: 'bronze' },
    { totalSpent: 20000, expected: 'silver' },
    { totalSpent: 49999, expected: 'silver' },
    { totalSpent: 50000, expected: 'gold' },
    { totalSpent: 100000, expected: 'gold' },
  ];

  it.each(cases)('累計 $totalSpent 円 → $expected', ({ totalSpent, expected }) => {
    expect(resolveMemberRank(totalSpent)).toBe(expected);
  });
});

describe('resolveDiscountRule の割引率', () => {
  const cases: { rank: MemberRank; expected: number }[] = [
    { rank: 'gold', expected: 1000 },
    { rank: 'silver', expected: 500 },
    { rank: 'bronze', expected: 300 },
    { rank: 'none', expected: 0 },
  ];

  it.each(cases)('$rank は小計10000円で $expected 円引き', ({ rank, expected }) => {
    expect(resolveDiscountRule(rank)(10000)).toBe(expected);
  });
});
