import type { Page } from 'playwright';
import { collectVitals, withPage } from '../vitals-client.ts';

/**
 * S07：同梱の Chromium で scheduler.yield と LoAF が使えるか、yieldToMain() が正しい方法を選んだか、
 * Web Worker 版だけが Worker を起動しているかを確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session07/verify-yield.ts
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const failures: string[] = [];

function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

const yesNo = (v: boolean): string => (v ? 'あり' : 'なし');

/** ページを開いて LCP を取ったあとにクリックし、機能の有無・起動された Worker の数・figure の属性を返す */
async function inspect(page: Page, pageName: string) {
  await collectVitals(page, `${TARGET}/pages/${pageName}/`);
  const support = await page.evaluate(() => ({
    schedulerYield: typeof (globalThis as { scheduler?: { yield?: unknown } }).scheduler?.yield === 'function',
    loaf: PerformanceObserver.supportedEntryTypes.includes('long-animation-frame'),
    longtask: PerformanceObserver.supportedEntryTypes.includes('longtask'),
  }));
  let workers = 0;
  page.on('worker', () => {
    workers += 1;
  });
  await page.click('button');
  await page.locator('figure polyline').waitFor({ timeout: 15_000 });
  await page.waitForTimeout(500);
  return {
    version: page.context().browser()?.version() ?? '不明',
    ...support,
    workers,
    strategy: await page.locator('figure').getAttribute('data-yield'),
  };
}

const chunked = await withPage((page) => inspect(page, 's07-chunked'));
const worker = await withPage((page) => inspect(page, 's07-worker'));

console.log(
  `Chromium ${chunked.version}（Playwright 1.63.0 同梱）: scheduler.yield ${yesNo(chunked.schedulerYield)}` +
    ` / long-animation-frame ${yesNo(chunked.loaf)} / longtask ${yesNo(chunked.longtask)}`,
);
console.log(`s07-chunked が選んだ譲り方: ${chunked.strategy ?? 'なし'}`);
console.log('');

const expected = chunked.schedulerYield ? 'scheduler.yield' : 'message-channel';
check('yieldToMain() がこのブラウザで使える一番よい方法を選んでいる', chunked.strategy === expected, `${chunked.strategy} / 期待 ${expected}`);
check('長いタスクを検知する手段（LoAF か longtask）がある', chunked.loaf || chunked.longtask);
check('タスク分割版は Worker を起動しない', chunked.workers === 0, `${chunked.workers} 個`);
check('Web Worker 版はクリックで Worker を 1 個起動する', worker.workers === 1, `${worker.workers} 個`);

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS07 の yield と Worker の検証に成功しました。');
