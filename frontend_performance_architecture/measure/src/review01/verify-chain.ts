import { CONDITIONS, measureMedian } from '../vitals-client.ts';

/**
 * 横断復習① 問題9：S04（クリティカルパス）と S05（大きい依存の分割）の改善前後を、
 * 1本のスクリプトで「根拠として使える形」の報告にまとめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/review01/verify-chain.ts
 * 時間の絶対値は環境で揺れるため、判定は比率と大小関係だけで行う。
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const RUNS = 3;
const failures: string[] = [];

function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

const ms = (v: number | undefined): string => (v === undefined ? 'なし' : `${Math.round(v).toLocaleString('en-US')}ms`);
const bytes = (v: number): string => `${v.toLocaleString('en-US')} バイト`;

type Row = { page: string; lcp: number | undefined; lcpRuns: number[]; jsBytes: number };
type Pair = { label: string; before: string; after: string; maxRatio: number };

async function measurePage(page: string): Promise<Row> {
  const { median, runs } = await measureMedian(`${TARGET}/pages/${page}/`, { runs: RUNS });
  const lcpRuns = runs.flatMap((r) => r.vitals.filter((v) => v.name === 'LCP').map((v) => v.value));
  return { page, lcp: median.LCP, lcpRuns, jsBytes: median.jsBytes ?? 0 };
}

// ① 計測より先に、条件と対象を確かめる。条件の違う数値を報告に混ぜないため
const { cpuThrottlingRate, network } = CONDITIONS;
check(
  '計測条件が本書の固定条件（CPU 4倍 / 1,500kbps / RTT 40ms）',
  cpuThrottlingRate === 4 && network.downloadKbps === 1_500 && network.latencyMs === 40,
);
check('計測対象が本番ビルド（preview）', new URL(TARGET).hostname.startsWith('preview'), TARGET);
if (failures.length > 0) {
  console.error('\n条件が揃っていないため計測しません。');
  process.exit(1);
}

// ② 改善前後の組を、同じスクリプト・同じ条件で続けて計測する
const pairs: Pair[] = [
  { label: 'S04 クリティカルパス', before: 's04-blocking', after: 's04-optimized', maxRatio: 0.7 },
  { label: 'S05 大きい依存の分割', before: 's05-print-eager', after: 's05-print-lazy', maxRatio: 0.85 },
];

console.log(
  `\n計測条件: CPU ${cpuThrottlingRate}倍スロットリング / ${network.downloadKbps.toLocaleString('en-US')}kbps / RTT ${network.latencyMs}ms / 本番ビルド（各${RUNS}回の中央値）\n`,
);
console.log('| 施策 | ページ | LCP 中央値 | LCP 各回 | 初期 JS |');
console.log('| :--- | :--- | ---: | :--- | ---: |');

const results: { pair: Pair; before: Row; after: Row }[] = [];
for (const pair of pairs) {
  const before = await measurePage(pair.before);
  const after = await measurePage(pair.after);
  for (const row of [before, after]) {
    console.log(`| ${pair.label} | ${row.page} | ${ms(row.lcp)} | ${row.lcpRuns.map((v) => ms(v)).join(' / ')} | ${bytes(row.jsBytes)} |`);
  }
  results.push({ pair, before, after });
}
console.log('');

// ③ 判定。時間は比率で、バイト数は下限で見る
for (const { pair, before, after } of results) {
  check(
    `${pair.before} と ${pair.after}: 各${RUNS}回すべてで LCP が取れている`,
    before.lcpRuns.length === RUNS && after.lcpRuns.length === RUNS,
  );
  if (before.lcp !== undefined && after.lcp !== undefined) {
    const ratio = after.lcp / before.lcp;
    check(`${pair.after} の LCP 中央値が ${pair.before} の ${pair.maxRatio} 倍以下`, ratio <= pair.maxRatio, `${ratio.toFixed(2)} 倍`);
  }
}

const s05 = results.find((r) => r.pair.before === 's05-print-eager');
if (s05) {
  const diff = s05.before.jsBytes - s05.after.jsBytes;
  check('s05-print-lazy の初期 JS が s05-print-eager より 30,000 バイト以上少ない', diff >= 30_000, bytes(diff));
}

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\n横断復習①の前後比較の検証に成功しました。');
