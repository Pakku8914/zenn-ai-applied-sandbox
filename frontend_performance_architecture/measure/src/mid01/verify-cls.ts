import { median } from '../vitals-client.ts';
import { clsOnce, conditionsLabel, createChecker, pageUrl, shiftSources } from './lab.ts';

/**
 * 中間プロジェクト：描画（CLS）の問題を確かめる。CLS は実行ごとに揺れるので各 5 回の中央値で判定する。
 * 実行: docker compose exec measure node --experimental-strip-types src/mid01/verify-cls.ts
 *
 * measureMedian は LCP の報告直後に値を読むため、LCP より後に差し込まれるバナーのずれを取りこぼす。
 * ここでは同じ部品（withPage・collectVitals・latestPerName・median）を lab.ts で組み合わせ、バナーの表示を待ってから読む。
 */
const RUNS = 5;
const PAGES = ['mid01-slow', 'mid01-fixed'] as const;
const { check, finish } = createChecker();

// 犯人探し：出題版で動いた要素と移動量
const shifts = await shiftSources(pageUrl('mid01-slow'));
console.log('mid01-slow で記録された layout-shift:');
for (const s of shifts) console.log(`  value=${s.value}  ${s.sources.join(' / ')}`);
check('出題版の layout-shift に、動いた要素（sources）が記録されている', shifts.some((s) => s.sources.length > 0), `${shifts.length} 件`);

const medians: Record<string, number> = {};
const table: { ページ: string; 各回: string; 中央値: number }[] = [];
for (const name of PAGES) {
  const values: number[] = [];
  for (let i = 0; i < RUNS; i += 1) values.push(await clsOnce(pageUrl(name)));
  medians[name] = median(values);
  table.push({ ページ: name, 各回: values.join(' / '), 中央値: medians[name]! });
}

console.log(`計測条件: ${conditionsLabel()}（各${RUNS}回）`);
console.table(table);

const slow = medians['mid01-slow'] ?? 0;
const fixed = medians['mid01-fixed'] ?? Number.NaN;
check('出題版の CLS 中央値が 0.1 以上（good の範囲を外れる）', slow >= 0.1, String(slow));
check('模範解答版の CLS 中央値が 0.1 未満（good）', fixed < 0.1, String(fixed));
check('模範解答版の CLS 中央値が出題版の 0.2 倍以下', fixed <= slow * 0.2, `${(fixed / slow).toFixed(2)} 倍`);

finish('中間プロジェクトの CLS');
