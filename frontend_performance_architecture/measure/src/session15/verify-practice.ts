import { collectVitals, jsBytes, withPage } from '../vitals-client.ts';
import { isRegressed, type BudgetRecord } from './budget.ts';
import { diffFiles, jsFiles, normalizeName } from './practice/files.ts';
import { proposeBudget } from './practice/propose.ts';
import { findFirstRegression } from './practice/regression.ts';
import { judgeSamples } from './practice/samples.ts';

/**
 * S15 練習問題の解答（問題5〜8）の検証。純粋関数は固定値で、jsFiles だけブラウザで確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session15/verify-practice.ts
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const failures: string[] = [];
function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}
const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b);

// 問題5：予算の提案
check('proposeBudget: 初期 JS 201,311 → 250,000', proposeBudget('jsBytes', 201_311) === 250_000);
check('proposeBudget: 初期 JS 208,333 → 250,000', proposeBudget('jsBytes', 208_333) === 250_000);
check('proposeBudget: 初期 JS 208,334 → 260,000', proposeBudget('jsBytes', 208_334) === 260_000);
check('proposeBudget: LCP 700 → 1,000', proposeBudget('LCP', 700) === 1_000);
check('proposeBudget: LCP 2,000 → 2,500（good の上限で頭打ち）', proposeBudget('LCP', 2_000) === 2_500);
check('proposeBudget: INP 56 → 100', proposeBudget('INP', 56) === 100);
check('proposeBudget: INP 264 → 200（good の上限で頭打ち）', proposeBudget('INP', 264) === 200);
check('proposeBudget: CLS は基準値によらず 0.1', proposeBudget('CLS', 0) === 0.1 && proposeBudget('CLS', 0.509) === 0.1);
let threw = false;
try {
  proposeBudget('LCP', -1);
} catch {
  threw = true;
}
check('proposeBudget: 負の基準値は例外', threw);

// 問題6：ばらつきを考慮した判定
check('judgeSamples: [652, 728, 700] / 1,000 → pass', same(judgeSamples([652, 728, 700], 1_000), { status: 'pass', median: 700, spread: 76 }));
check('judgeSamples: 2 回だけ → insufficient', judgeSamples([652, 728], 1_000).status === 'insufficient');
check('judgeSamples: 0 回 → insufficient', same(judgeSamples([], 1_000), { status: 'insufficient', median: undefined, spread: undefined }));
check('judgeSamples: [980, 1020, 1010] / 1,000 → fail', same(judgeSamples([980, 1_020, 1_010], 1_000), { status: 'fail', median: 1_010, spread: 40 }));
check('judgeSamples: 上限ちょうどは pass', judgeSamples([1_000, 1_000, 1_000], 1_000).status === 'pass');
check('judgeSamples: CLS [0, 0, 0.509] / 0.1 → unstable', judgeSamples([0, 0, 0.509], 0.1).status === 'unstable');

// 問題7：最初の回帰を探す
const rec = (commit: string, jsBytes: number, LCP?: number): BudgetRecord => ({
  name: 'catalog',
  url: `${TARGET}/`,
  measuredAt: '2026-09-30T00:00:00.000Z',
  commit,
  conditions: 'fixture',
  runs: 3,
  median: LCP === undefined ? { jsBytes } : { jsBytes, LCP },
  samples: {},
});
check('isRegressed: 初期 JS +1,000 は要確認にしない / +1,001 は要確認', !isRegressed('jsBytes', 201_000, 202_000) && isRegressed('jsBytes', 201_000, 202_001));
check('isRegressed: LCP +20% ちょうどは要確認にしない / それを超えたら要確認', !isRegressed('LCP', 700, 840) && isRegressed('LCP', 700, 841));
const history = [rec('a1', 201_311, 700), rec('a2', 201_500, 760), rec('a3', 201_480), rec('a4', 322_000, 1_180), rec('a5', 322_100, 1_150)];
const byBytes = findFirstRegression(history, 'jsBytes');
check('findFirstRegression: 初期 JS は a3 → a4', byBytes?.from.commit === 'a3' && byBytes.to.commit === 'a4');
const byLcp = findFirstRegression(history, 'LCP');
check('findFirstRegression: LCP は値の無い a3 を飛ばして a2 → a4', byLcp?.from.commit === 'a2' && byLcp.to.commit === 'a4');
const noisy = [rec('b1', 201_311, 700), rec('b2', 201_311, 900), rec('b3', 201_311, 700)];
check('findFirstRegression: 初期 JS が変わらない揺れは初期 JS では見つからない', findFirstRegression(noisy, 'jsBytes') === undefined);
check('findFirstRegression: LCP だけ見ると揺れを回帰と取り違える（b2）', findFirstRegression(noisy, 'LCP')?.to.commit === 'b2');

// 問題8：ファイルごとの差分
check('normalizeName: ハッシュを取り除く', normalizeName('/assets/modulepreload-polyfill-B5Qt9EMX.js') === '/assets/modulepreload-polyfill.js');
const previous = [
  { file: '/assets/main-AbCd1234.js', bytes: 3_000 },
  { file: '/assets/client-Xy_9-k2L.js', bytes: 198_000 },
  { file: '/assets/old-chart-Aa11Bb22.js', bytes: 5_000 },
];
const current = [
  { file: '/assets/main-ZZZZ9999.js', bytes: 3_200 },
  { file: '/assets/client-Qw8e_r7T.js', bytes: 198_000 },
  { file: '/assets/renderPrintCard-P0o9i8U7.js', bytes: 120_000 },
];
const diff = diffFiles(previous, current);
check(
  'diffFiles: 増減の大きい順（追加 +120,000 → 削除 −5,000 → +200）、変化なしは除く',
  same(diff, [
    { name: '/assets/renderPrintCard.js', previous: 0, current: 120_000, delta: 120_000 },
    { name: '/assets/old-chart.js', previous: 5_000, current: 0, delta: -5_000 },
    { name: '/assets/main.js', previous: 3_000, current: 3_200, delta: 200 },
  ]),
);

// jsFiles：実際のページで、ファイルごとの合計が jsBytes と一致する
await withPage(async (page) => {
  await collectVitals(page, `${TARGET}/`);
  const files = await jsFiles(page);
  const total = await jsBytes(page);
  const sum = files.reduce((s, f) => s + f.bytes, 0);
  check('jsFiles: ファイルごとの合計が jsBytes と一致する', files.length > 0 && sum === total, `${files.length} ファイル / ${sum.toLocaleString('en-US')} バイト`);
});

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS15 練習問題の検証に成功しました。');
