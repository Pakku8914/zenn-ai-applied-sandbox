import { collectVitals, interactAndCollect, latestPerName, median, withPage } from '../vitals-client.ts';
import { KEYWORD, TARGET, conditionsLabel, createChecker, matchedFor, ms, waitForCount } from './helpers.ts';

/**
 * S11：全件描画と仮想化を、2,000 件と 20,000 件で LCP と入力 INP の中央値で比べる（各 3 回）。
 * 時間の値は実行ごとに揺れるので、大小関係と比率で判定する。
 * 実行: docker compose exec measure node --experimental-strip-types src/session11/verify-vitals.ts
 */
const RUNS = 3;
/** web-vitals は既定で 40ms 未満の操作を INP の候補にしない。報告されなかった回は 40ms として数える */
const INP_REPORT_THRESHOLD_MS = 40;
const PAGES = [
  { name: 's11-plain-2k', total: 2_000 },
  { name: 's11-plain-20k', total: 20_000 },
  { name: 's11-virtual-2k', total: 2_000 },
  { name: 's11-virtual-20k', total: 20_000 },
] as const;
const { check, finish } = createChecker();

async function once(name: string, total: number): Promise<{ lcp: number; inp: number | null }> {
  return withPage(async (page) => {
    // LCP を取り終えてから入力する（先に入力すると LCP が取れなくなる）
    await collectVitals(page, `${TARGET}/pages/${name}/`);
    await interactAndCollect(page, '#keyword', KEYWORD);
    await waitForCount(page, matchedFor(total));
    await page.waitForTimeout(300); // INP の報告が web-vitals に届くのを待つ
    const vitals = latestPerName(await page.evaluate(() => window.__webVitals ?? []));
    return {
      lcp: vitals.find((v) => v.name === 'LCP')?.value ?? Number.NaN,
      inp: vitals.find((v) => v.name === 'INP')?.value ?? null,
    };
  });
}

console.log(`計測条件: ${conditionsLabel()}（各${RUNS}回の中央値）`);
console.log(`入力: #keyword に「${KEYWORD}」（pressSequentially）`);

const lcp: Record<string, number> = {};
const inp: Record<string, number> = {};
for (const p of PAGES) {
  const runs: { lcp: number; inp: number | null }[] = [];
  for (let i = 0; i < RUNS; i += 1) runs.push(await once(p.name, p.total));
  lcp[p.name] = median(runs.map((r) => r.lcp));
  inp[p.name] = median(runs.map((r) => r.inp ?? INP_REPORT_THRESHOLD_MS));
  const unreported = runs.filter((r) => r.inp === null).length;
  console.log(
    `${p.name}: LCP ${ms(lcp[p.name])} / 入力 INP ${ms(inp[p.name])}${unreported > 0 ? `（${unreported}回は40ms未満で未報告）` : ''}`,
  );
}
console.log('');

const get = (table: Record<string, number>, name: string): number => table[name] ?? Number.NaN;
const lcpPlain2k = get(lcp, 's11-plain-2k');
const lcpPlain20k = get(lcp, 's11-plain-20k');
const lcpVirtual2k = get(lcp, 's11-virtual-2k');
const lcpVirtual20k = get(lcp, 's11-virtual-20k');
const inpPlain2k = get(inp, 's11-plain-2k');
const inpPlain20k = get(inp, 's11-plain-20k');
const inpVirtual2k = get(inp, 's11-virtual-2k');
const inpVirtual20k = get(inp, 's11-virtual-20k');

// 全件描画は件数に比例して悪くなる
check('全件描画版は 20,000 件のほうが 2,000 件より LCP が大きい', lcpPlain20k > lcpPlain2k, `${ms(lcpPlain2k)} → ${ms(lcpPlain20k)}`);
check('全件描画版（20,000 件）の入力 INP が 200ms 以上（good の境界を超えている）', inpPlain20k >= 200, ms(inpPlain20k));

// 仮想化すると 20,000 件でも大きく改善する
const lcpRatio = lcpVirtual20k / lcpPlain20k;
const inpRatio = inpVirtual20k / inpPlain20k;
check('仮想化版（20,000 件）の LCP が全件描画版の 0.7 倍以下', lcpRatio <= 0.7, `${lcpRatio.toFixed(2)} 倍`);
check('仮想化版（20,000 件）の入力 INP が全件描画版の 0.5 倍以下', inpRatio <= 0.5, `${inpRatio.toFixed(2)} 倍`);
check('仮想化版（20,000 件）の入力 INP が 200ms 未満（good）', inpVirtual20k < 200, ms(inpVirtual20k));

// 件数を 10 倍にしたときの伸び方：仮想化版は全件描画版よりずっと小さい
const growth = (small: number, large: number): number => large / small;
const lcpGrowthPlain = growth(lcpPlain2k, lcpPlain20k);
const lcpGrowthVirtual = growth(lcpVirtual2k, lcpVirtual20k);
const inpGrowthPlain = growth(inpPlain2k, inpPlain20k);
const inpGrowthVirtual = growth(inpVirtual2k, inpVirtual20k);
check('仮想化版は件数を 10 倍にしても LCP が 1.3 倍以内', lcpGrowthVirtual <= 1.3, `${lcpGrowthVirtual.toFixed(2)} 倍`);
check(
  '件数を 10 倍にしたときの LCP の伸びは、仮想化版のほうが小さい',
  lcpGrowthVirtual < lcpGrowthPlain,
  `全件描画 ${lcpGrowthPlain.toFixed(2)} 倍 / 仮想化 ${lcpGrowthVirtual.toFixed(2)} 倍`,
);
check(
  '件数を 10 倍にしたときの INP の伸びは、仮想化版のほうが小さい',
  inpGrowthVirtual < inpGrowthPlain,
  `全件描画 ${inpGrowthPlain.toFixed(2)} 倍 / 仮想化 ${inpGrowthVirtual.toFixed(2)} 倍`,
);

finish('S11 の LCP・INP');
