// 問題3：optional chaining（?.）と Null 合体演算子（??）。
import { findProductById } from '../cart';
import { DISCOUNT_PERCENT_BY_RANK } from '../constants';
import type { CartLine, MemberRank } from '../types';

/** 今回のキャンペーン設定。silver は「今回は割引0%」を意図して 0 を入れている */
const CAMPAIGN_PERCENT: Partial<Record<MemberRank, number>> = { gold: 15, silver: 0 };

/** 商品名。見つからなければ既定の文字列 */
export function productName(id: number): string {
  return findProductById(id)?.name ?? '(不明な商品)';
}

/** 商品名の文字数。?. は左が undefined ならそこで打ち切る */
export function nameLength(id: number): number {
  return findProductById(id)?.name.length ?? 0;
}

/** 先頭の明細の商品名。空配列でも落ちない */
export function firstProductName(lines: readonly CartLine[]): string {
  return lines[0]?.product.name ?? '(カートは空です)';
}

/** Good: ?? は null / undefined のときだけ既定値を使う */
export function campaignPercent(rank: MemberRank): number {
  return CAMPAIGN_PERCENT[rank] ?? DISCOUNT_PERCENT_BY_RANK[rank];
}

/** Bad: || は 0 も「値が無い」と見なすので、意図した 0% が消える */
export function campaignPercentBad(rank: MemberRank): number {
  return CAMPAIGN_PERCENT[rank] || DISCOUNT_PERCENT_BY_RANK[rank];
}

export function formatNullSafety(lines: readonly CartLine[]): string {
  const emptyLines: readonly CartLine[] = [];

  return [
    `id=1 の商品名: ${productName(1)}`,
    `id=99 の商品名: ${productName(99)}`,
    `id=1 の商品名の文字数: ${nameLength(1)}`,
    `id=99 の商品名の文字数: ${nameLength(99)}`,
    `先頭の明細: ${firstProductName(lines)}`,
    `空のカートの先頭: ${firstProductName(emptyLines)}`,
    `silver のキャンペーン割引（?? 版）: ${campaignPercent('silver')}%`,
    `silver のキャンペーン割引（|| 版）: ${campaignPercentBad('silver')}%`,
    `bronze のキャンペーン割引（?? 版）: ${campaignPercent('bronze')}%`,
    `gold のキャンペーン割引（?? 版）: ${campaignPercent('gold')}%`,
  ].join('\n');
}
