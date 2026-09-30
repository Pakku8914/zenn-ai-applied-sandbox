import { collectVitals, interactAndCollect, latestPerName, withPage } from '../vitals-client.ts';
import { measureKeywordInput } from './measure-keyword.ts';

/**
 * S03：計測の落とし穴を実物で確かめる。
 * いずれも「エラーは出ないのに値が取れない／おかしい」種類の問題なので、検証で固定しておく。
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const failures: string[] = [];
function check(name: string, ok: boolean, detail: string): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name} — ${detail}`);
  if (!ok) failures.push(name);
}

declare global {
  interface Window {
    __lcpDefault?: number;
  }
}

// 1. LCP は getEntriesByType では取れず、buffered な PerformanceObserver でだけ取れる
// 2. page.fill() では画面は変わるが INP は報告されない
await withPage(async (page) => {
  await collectVitals(page, TARGET);

  const viaGetEntries = await page.evaluate(
    () => performance.getEntriesByType('largest-contentful-paint').length,
  );
  const viaObserver = await page.evaluate(
    () =>
      new Promise<{ count: number; tag: string }>((resolve) => {
        new PerformanceObserver((list) => {
          const entries = list.getEntries();
          const last = entries.at(-1) as (PerformanceEntry & { element?: Element | null }) | undefined;
          resolve({ count: entries.length, tag: last?.element?.tagName ?? 'なし' });
        }).observe({ type: 'largest-contentful-paint', buffered: true });
        setTimeout(() => resolve({ count: 0, tag: 'なし' }), 3_000);
      }),
  );
  check('getEntriesByType では LCP エントリが 0 件', viaGetEntries === 0, `${viaGetEntries} 件`);
  check('buffered な PerformanceObserver では LCP エントリが取れる', viaObserver.count > 0, `${viaObserver.count} 件`);
  check('LCP の要素は見出し（H1）', viaObserver.tag === 'H1', viaObserver.tag);

  await page.fill('#keyword', '商品1');
  await page.waitForTimeout(800);
  const items = await page.locator('section ul li').count();
  const afterFill = latestPerName(await page.evaluate(() => window.__webVitals ?? []));
  check('page.fill でも絞り込み自体は効く', items === 1111, `${items} 件`);
  check('page.fill では INP が報告されない', !afterFill.some((v) => v.name === 'INP'),
    afterFill.map((v) => v.name).join(', '));
});

// 3. 修正版（LCP → 実キー入力の順）なら LCP と INP の両方が取れる
const fixed = await measureKeywordInput(TARGET);
const names = fixed.map((v) => v.name);
check('修正版では LCP と INP の両方が取れる', names.includes('LCP') && names.includes('INP'),
  fixed.map((v) => `${v.name}=${v.value}`).join(', '));

// 4. reportAllChanges を付けない既定の onLCP は、入力前には報告しない
await withPage(async (page) => {
  const vitals = await collectVitals(page, `${TARGET}/pages/s03-lcp-default/`);
  const lcpAll = vitals.find((v) => v.name === 'LCP');
  const before = await page.evaluate(() => window.__lcpDefault ?? null);
  check('reportAllChanges ありは入力前に LCP を報告する', lcpAll !== undefined, `${lcpAll?.value}ms`);
  check('既定の onLCP は入力前には報告しない', before === null, `${before ?? '未報告'}`);

  await interactAndCollect(page, '#keyword', '商品1');
  const after = await page.evaluate(() => window.__lcpDefault ?? null);
  check('既定の onLCP は入力のあとで確定値を報告する', after !== null, `${after ?? '未報告'}ms`);
});

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS03 落とし穴の検証に成功しました。');
