import { KB, type Metric } from '../budget.ts';

/** web-vitals が「良い（good）」とする上限。予算をこれより緩くしない */
export const GOOD_LIMIT = { LCP: 2_500, INP: 200, CLS: 0.1 } as const;

/**
 * 問題5：基準値（出発点の実測の中央値）から予算を提案する。
 * - 初期 JS：基準値の 1.2 倍を 10KB 単位で切り上げ（決定的なので余裕は小さく）
 * - LCP・INP：基準値の 1.4 倍を 100ms 単位で切り上げ、good の上限を超えない（揺れるので余裕は大きく）
 * - CLS：実行ごとに 0 と大きな値を行き来するので、基準値から倍率で作らず good の上限をそのまま使う
 * 小数の倍率（1.2・1.4）を掛けると誤差で切り上げ先がずれるため、整数の掛け算と割り算で計算する。
 */
export function proposeBudget(metric: Metric, baseline: number): number {
  if (!Number.isFinite(baseline) || baseline < 0) throw new Error(`基準値が不正です: ${baseline}`);
  if (metric === 'jsBytes') return Math.ceil((baseline * 12) / (100 * KB)) * 10 * KB;
  if (metric === 'CLS') return GOOD_LIMIT.CLS;
  return Math.min(Math.ceil((baseline * 14) / 1_000) * 100, GOOD_LIMIT[metric]);
}
