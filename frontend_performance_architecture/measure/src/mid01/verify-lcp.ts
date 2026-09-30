import { collectVitals, measureMedian, withPage } from '../vitals-client.ts';
import { PAGE_TAG_MS, conditionsLabel, createChecker, lcpElement, ms, n, pageUrl, type LcpInfo } from './lab.ts';

/**
 * 中間プロジェクト：読み込み（LCP）の問題と、おとり（グラフの遅延読み込み）を確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/mid01/verify-lcp.ts
 *
 *   mid01-slow       … 出題版（<head> で同期の計測タグを実行）
 *   mid01-fixed      … 模範解答版（計測タグを load の後に回した）
 *   mid01-lazy-chart … 模範解答版のグラフだけを React.lazy にした比較用
 * 時間は大小関係と比率で、LCP 要素は完全一致で判定する。
 */
const PAGES = ['mid01-slow', 'mid01-fixed', 'mid01-lazy-chart'] as const;
const { check, finish } = createChecker();

console.log(`計測条件: ${conditionsLabel()}（各3回の中央値）`);

const medians: Record<string, Record<string, number>> = {};
for (const name of PAGES) {
  const { median } = await measureMedian(pageUrl(name), { runs: 3 });
  medians[name] = median;
  console.log(`${name.padEnd(16)}: LCP ${ms(median.LCP)} / TTFB ${ms(median.TTFB)} / 初期 JS ${n(median.jsBytes ?? 0)} バイト`);
}

// LCP 要素を調べる（原因の切り分けの根拠：LCP 要素が JS に依存するかどうか）
const elements: Record<string, LcpInfo> = {};
for (const name of ['mid01-slow', 'mid01-fixed'] as const) {
  elements[name] = await withPage(async (page) => {
    await collectVitals(page, pageUrl(name));
    return lcpElement(page);
  });
  const e = elements[name]!;
  console.log(`${name.padEnd(16)}: LCP 要素 ${e.tag}${e.className ? `.${e.className}` : ''}（size ${n(e.size)}）`);
}
console.log('');

const slow = medians['mid01-slow']!;
const fixed = medians['mid01-fixed']!;
const lazyChart = medians['mid01-lazy-chart']!;

for (const name of ['mid01-slow', 'mid01-fixed'] as const) {
  const e = elements[name]!;
  check(`${name} の LCP 要素は HTML に直接書いた導入文（P.lead）`, e.tag === 'P' && e.className === 'lead', `${e.tag}.${e.className}`);
}

if (slow.LCP === undefined || fixed.LCP === undefined || lazyChart.LCP === undefined) {
  check('3 ページすべてで LCP が計測できている', false);
} else {
  check(`出題版の LCP が計測タグの占有時間（${PAGE_TAG_MS}ms）以上`, slow.LCP >= PAGE_TAG_MS, ms(slow.LCP));
  const ratio = fixed.LCP / slow.LCP;
  check('模範解答版の LCP 中央値が出題版の 0.7 倍以下', ratio <= 0.7, `${ratio.toFixed(2)} 倍`);

  // おとり：グラフを遅延読み込みにしても、LCP は改善の基準（0.7 倍以下）に届かない
  const lazyRatio = lazyChart.LCP / fixed.LCP;
  check('グラフを遅延読み込みにしても LCP は 0.7 倍以下にならない（改善の基準に届かない）', lazyRatio > 0.7, `${lazyRatio.toFixed(2)} 倍`);
}

// 初期 JS の差は決定的な値。遅延読み込みで減る（または増える）のは 2% 未満
const fixedJs = fixed.jsBytes ?? 0;
const lazyJs = lazyChart.jsBytes ?? 0;
const diff = fixedJs - lazyJs;
check('模範解答版の初期 JS が計測できている', fixedJs > 0, `${n(fixedJs)} バイト`);
check(
  'グラフを遅延読み込みにしたときの初期 JS の変化は 2% 未満',
  Math.abs(diff) / fixedJs < 0.02,
  `${diff >= 0 ? '−' : '+'}${n(Math.abs(diff))} バイト（${((Math.abs(diff) / fixedJs) * 100).toFixed(2)}%）`,
);

finish('中間プロジェクトの LCP');
