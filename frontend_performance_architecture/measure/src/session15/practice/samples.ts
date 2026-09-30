import { median } from '../../vitals-client.ts';

export type SampleStatus = 'pass' | 'fail' | 'insufficient' | 'unstable';
export type SampleJudge = { status: SampleStatus; median: number | undefined; spread: number | undefined };

/**
 * 問題6：複数回の計測値から、ばらつきを考慮して合否を決める。
 * - 回数が minRuns 未満：insufficient（1回だけの値で合否を決めない）
 * - 揺れ幅（最大 − 最小）が予算の半分を超える：unstable（この予算では判定できない）
 * - それ以外は中央値で判定（上限ちょうどは合格）
 */
export function judgeSamples(samples: readonly number[], max: number, minRuns = 3): SampleJudge {
  if (samples.length === 0) return { status: 'insufficient', median: undefined, spread: undefined };
  const m = median(samples);
  const spread = Math.max(...samples) - Math.min(...samples);
  if (samples.length < minRuns) return { status: 'insufficient', median: m, spread };
  if (spread > max / 2) return { status: 'unstable', median: m, spread };
  return { status: m <= max ? 'pass' : 'fail', median: m, spread };
}
