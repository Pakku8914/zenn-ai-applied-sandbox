import { CONDITIONS, collectVitals, jsBytes, measureMedian, withPage } from '../vitals-client.ts';

/**
 * S05：分割の前後で、初期 JS 量（jsBytes）と LCP を同じ条件で3回ずつ計測して比べる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session05/verify-split.ts
 * jsBytes は決定的なので大小で、LCP は時間なので大小関係と比率で判定する。
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const failures: string[] = [];

function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

const ms = (v: number | undefined): string => (v === undefined ? 'なし' : `${Math.round(v).toLocaleString('en-US')}ms`);
const bytes = (v: number): string => `${v.toLocaleString('en-US')} バイト`;
const url = (page: string): string => (page === 'main' ? `${TARGET}/` : `${TARGET}/pages/${page}/`);

async function measurePage(page: string): Promise<{ LCP: number | undefined; jsBytes: number }> {
  const { median } = await measureMedian(url(page), { runs: 3 });
  const row = { LCP: median.LCP, jsBytes: median.jsBytes ?? 0 };
  console.log(`${page.padEnd(16)}: 初期 JS ${bytes(row.jsBytes).padStart(15)} / LCP ${ms(row.LCP)}`);
  return row;
}

const { cpuThrottlingRate, network } = CONDITIONS;
console.log(
  `計測条件: CPU ${cpuThrottlingRate}倍スロットリング / ${network.downloadKbps.toLocaleString('en-US')}kbps / RTT ${network.latencyMs}ms / 本番ビルド（各3回の中央値）`,
);

const main = await measurePage('main');
const lazyChart = await measurePage('s05-lazy-chart');
const eager = await measurePage('s05-print-eager');
const lazyPrint = await measurePage('s05-print-lazy');
const overSplit = await measurePage('s05-over-split');
console.log('');

// 1. HeavyChart の遅延読み込み：差は小さい。悪化していないことだけを確かめる
const chartDiff = lazyChart.jsBytes - main.jsBytes;
check('s05-lazy-chart と出発点の初期 JS の差は 5,000 バイト未満', Math.abs(chartDiff) < 5_000, `${chartDiff >= 0 ? '+' : ''}${bytes(chartDiff)}`);
if (main.LCP !== undefined && lazyChart.LCP !== undefined) {
  const ratio = lazyChart.LCP / main.LCP;
  check('s05-lazy-chart の LCP が出発点の 1.5 倍以内（悪化していない）', ratio <= 1.5, `${ratio.toFixed(2)} 倍`);
} else {
  check('出発点と s05-lazy-chart で LCP が計測できている', false);
}

// 2. 大きな依存の遅延読み込み：初期 JS が減り、LCP が縮む
const printDiff = eager.jsBytes - lazyPrint.jsBytes;
check('s05-print-lazy の初期 JS が s05-print-eager より 30,000 バイト以上少ない', printDiff >= 30_000, bytes(printDiff));
if (eager.LCP !== undefined && lazyPrint.LCP !== undefined) {
  const ratio = lazyPrint.LCP / eager.LCP;
  check('s05-print-lazy の LCP 中央値が s05-print-eager の 0.85 倍以下', ratio <= 0.85, `${ratio.toFixed(2)} 倍`);
} else {
  check('印刷系の2ページで LCP が計測できている', false);
}

// 3. 分割しすぎ：見出しまでに往復が積み重なり、LCP が出発点より遅れる
if (main.LCP !== undefined && overSplit.LCP !== undefined) {
  check('s05-over-split の LCP 中央値が出発点より大きい', overSplit.LCP > main.LCP, `${ms(overSplit.LCP)} > ${ms(main.LCP)}`);
} else {
  check('s05-over-split で LCP が計測できている', false);
}

// 4. 遅延読み込みが実際に働くこと：押したときに初めてチャンクが取得される
await withPage(async (page) => {
  await collectVitals(page, url('s05-lazy-chart'));
  const before = await jsBytes(page);
  await page.getByRole('button', { name: 'グラフを表示' }).click();
  await page.locator('figure svg').waitFor({ timeout: 15_000 });
  const added = (await jsBytes(page)) - before;
  check('s05-lazy-chart: ボタンを押すとグラフのチャンクが取得されて表示される', added > 0, `+${bytes(added)}`);
});

await withPage(async (page) => {
  await collectVitals(page, url('s05-print-lazy'));
  const before = await jsBytes(page);
  await page.locator('#print-button').click();
  await page.locator('#print-output', { hasText: '<article class="print-card">' }).waitFor({ timeout: 15_000 });
  const added = (await jsBytes(page)) - before;
  check('s05-print-lazy: ボタンを押すと react-dom/server のチャンクが取得される（30,000 バイト以上）', added >= 30_000, `+${bytes(added)}`);
});

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS05 の分割の計測の検証に成功しました。');
