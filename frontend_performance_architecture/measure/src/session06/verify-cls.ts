import { collectVitals, latestPerName, median, withPage } from '../vitals-client.ts';
import { TARGET, conditionsLabel, createChecker } from './lab.ts';

/**
 * S06：後から挿入されるバナーの CLS を、Bad（late）と Good（reserved・overlay）で比べる。
 * CLS は実行ごとに揺れるので、各ページ 5 回計測して中央値で判定する。
 * 実行: docker compose exec measure node --experimental-strip-types src/session06/verify-cls.ts
 *
 * measureMedian は LCP の報告直後に値を読むため、300ms 後に差し込まれるバナーのずれを取りこぼす。
 * ここでは同じ部品（withPage・collectVitals・latestPerName・median）を使い、バナーの表示を待ってから読む。
 */
const RUNS = 5;
const PAGES = ['s06-banner-late', 's06-banner-reserved', 's06-banner-overlay'] as const;
const { check, finish } = createChecker();

async function clsOnce(pageName: string): Promise<number> {
  return withPage(async (page) => {
    await collectVitals(page, `${TARGET}/pages/${pageName}/`);
    await page.waitForSelector('[data-campaign="loaded"]', { timeout: 10_000 });
    await page.waitForTimeout(500); // layout-shift の報告が web-vitals に届くのを待つ。入力はしない
    const vitals = latestPerName(await page.evaluate(() => window.__webVitals ?? []));
    return vitals.find((v) => v.name === 'CLS')?.value ?? 0; // ずれが一度もなければ CLS は報告されない＝0
  });
}

type Shift = { value: number; sources: string[] };

/** layout-shift エントリの sources から「どの要素が・どこからどこへ」動いたかを読む（犯人探し） */
async function shiftSources(pageName: string): Promise<Shift[]> {
  return withPage(async (page) => {
    await collectVitals(page, `${TARGET}/pages/${pageName}/`);
    await page.waitForSelector('[data-campaign="loaded"]', { timeout: 10_000 });
    await page.waitForTimeout(500);
    return page.evaluate(
      () =>
        new Promise<Shift[]>((resolve) => {
          // layout-shift は getEntriesByType では取れないので、buffered: true の observer で過去分を受け取る
          new PerformanceObserver((list) => {
            resolve(
              list.getEntries().map((entry) => {
                const shift = entry as PerformanceEntry & {
                  value: number;
                  sources?: { node?: Node | null; previousRect: DOMRectReadOnly; currentRect: DOMRectReadOnly }[];
                };
                return {
                  value: Math.round(shift.value * 1000) / 1000,
                  sources: (shift.sources ?? []).map(
                    (s) => `${s.node?.nodeName ?? '（削除済み）'} y=${Math.round(s.previousRect.y)}→${Math.round(s.currentRect.y)}`,
                  ),
                };
              }),
            );
          }).observe({ type: 'layout-shift', buffered: true });
          setTimeout(() => resolve([]), 1_000); // ずれが一度もなければ observer は呼ばれない
        }),
    );
  });
}

const lateShifts = await shiftSources('s06-banner-late');
console.log('s06-banner-late で記録された layout-shift:');
for (const s of lateShifts) console.log(`  value=${s.value}  ${s.sources.join(' / ')}`);
check('Bad（late）の layout-shift に、動いた要素（sources）が記録されている', lateShifts.some((s) => s.sources.length > 0), `${lateShifts.length} 件`);

const medians: Record<string, number> = {};
const table: { ページ: string; 各回: string; 中央値: number }[] = [];
for (const name of PAGES) {
  const values: number[] = [];
  for (let i = 0; i < RUNS; i += 1) values.push(await clsOnce(name));
  medians[name] = median(values);
  table.push({ ページ: name, 各回: values.join(' / '), 中央値: medians[name]! });
}

console.log(`計測条件: ${conditionsLabel()}（各${RUNS}回）`);
console.table(table);

const late = medians['s06-banner-late'] ?? 0;
check('Bad（late）の CLS 中央値が 0.1 以上（good の範囲を外れる）', late >= 0.1, String(late));
for (const good of ['s06-banner-reserved', 's06-banner-overlay']) {
  const value = medians[good] ?? Number.NaN;
  check(`${good} の CLS 中央値が 0.1 未満（good）`, value < 0.1, String(value));
  check(`${good} の CLS 中央値が Bad の 0.2 倍以下`, value <= late * 0.2, `${(value / late).toFixed(2)} 倍`);
}

finish('S06 の CLS');
