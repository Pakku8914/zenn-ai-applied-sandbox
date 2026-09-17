// 問題3の解答：循環参照を解いたあとの「共通の土台」。
// 型と定数だけを置き、他のファイルを1つも import しない。

export type MemberRank = 'gold' | 'silver' | 'bronze' | 'none';

/**
 * 会員ランクごとの割引率（%）。
 * as const で 10 / 5 / 3 / 0 というリテラル型のまま保ち、
 * satisfies で「MemberRank を網羅しているか」だけを検査させる。
 */
export const DISCOUNT_PERCENT_BY_RANK = {
  gold: 10,
  silver: 5,
  bronze: 3,
  none: 0,
} as const satisfies Record<MemberRank, number>;
