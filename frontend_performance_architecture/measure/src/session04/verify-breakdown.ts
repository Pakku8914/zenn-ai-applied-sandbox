import { CONDITIONS, measureMedian } from '../vitals-client.ts';

/**
 * S04 練習問題7：改善の効果を要因ごとに分ける。
 * Bad 版 → 同期スクリプトだけ外した版 → 最適化した版 の3ページを同じ条件で3回ずつ計測する。
 * 実行: docker compose exec measure node --experimental-strip-types src/session04/verify-breakdown.ts
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const failures: string[] = [];

function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

const ms = (v: number): string => `${Math.round(v).toLocaleString('en-US')}ms`;

const { cpuThrottlingRate, network } = CONDITIONS;
console.log(
  `計測条件: CPU ${cpuThrottlingRate}倍スロットリング / ${network.downloadKbps.toLocaleString('en-US')}kbps / RTT ${network.latencyMs}ms / 本番ビルド（各3回の中央値）`,
);

const pages = ['s04-blocking', 's04-no-tag', 's04-optimized'] as const;
const lcp: Record<string, number> = {};
for (const page of pages) {
  const { median } = await measureMedian(`${TARGET}/pages/${page}/`, { runs: 3 });
  if (median.LCP === undefined) {
    check(`${page} の LCP が計測できている`, false);
    continue;
  }
  lcp[page] = median.LCP;
  console.log(`${page.padEnd(13)}: LCP ${ms(median.LCP)}`);
}

const blocking = lcp['s04-blocking'];
const noTag = lcp['s04-no-tag'];
const optimized = lcp['s04-optimized'];
if (blocking !== undefined && noTag !== undefined && optimized !== undefined) {
  console.log(`同期スクリプトを外した効果      : ${ms(blocking - noTag)}`);
  console.log(`CSS と画像の指定を直した効果    : ${ms(noTag - optimized)}`);
  check('LCP の中央値が optimized < no-tag < blocking の順に並ぶ', optimized < noTag && noTag < blocking);
}

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS04 の要因分解の検証に成功しました。');
