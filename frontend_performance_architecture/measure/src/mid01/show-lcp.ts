import { collectVitals, withPage } from '../vitals-client.ts';
import { lcpElement, ms, n, pageUrl } from './lab.ts';

/**
 * 中間プロジェクト 問題2 の解答例：LCP 要素と、TTFB・FCP・LCP の時刻を並べて出す（判定はしない）。
 * 実行: docker compose exec measure node --experimental-strip-types src/mid01/show-lcp.ts mid01-slow
 */
const name = process.argv[2] ?? 'mid01-slow';

const result = await withPage(async (page) => {
  const vitals = await collectVitals(page, pageUrl(name));
  const element = await lcpElement(page);
  // FCP は paint エントリから読める（LCP と違い getEntriesByType で取れる）
  const fcp = await page.evaluate(
    () => performance.getEntriesByType('paint').find((e) => e.name === 'first-contentful-paint')?.startTime ?? null,
  );
  return { vitals, element, fcp };
});

const pick = (metric: string): number | undefined => result.vitals.find((v) => v.name === metric)?.value;
const { tag, className, size } = result.element;
console.log(`対象: ${name}`);
console.log(`LCP 要素: ${tag}${className ? `.${className}` : ''}（size ${n(size)}）`);
console.log(`TTFB ${ms(pick('TTFB'))} / FCP ${ms(result.fcp)} / LCP ${ms(pick('LCP'))}`);
