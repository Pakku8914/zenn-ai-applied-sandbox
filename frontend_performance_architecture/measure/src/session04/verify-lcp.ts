import { CONDITIONS, measureMedian } from '../vitals-client.ts';

/**
 * S04：レンダリングを妨げる版（Bad）と最適化した版（Good）の LCP を、同じ条件で3回ずつ計測して比べる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session04/verify-lcp.ts
 * 時間の絶対値は環境で揺れるため、判定は大小関係と比率だけで行う。
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
// app/src/sessions/s04/third-party-tag.ts の TAG_BLOCKING_MS と同じ値（擬似タグがメインスレッドを占有する時間）
const TAG_BLOCKING_MS = 300;
const failures: string[] = [];

function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

const ms = (v: number | undefined): string => (v === undefined ? 'なし' : `${Math.round(v).toLocaleString('en-US')}ms`);

async function measurePage(page: string): Promise<Record<string, number>> {
  const { median } = await measureMedian(`${TARGET}/pages/${page}/`, { runs: 3 });
  console.log(`${page.padEnd(13)}: LCP ${ms(median.LCP)} / CLS ${median.CLS ?? 'なし'} / TTFB ${ms(median.TTFB)}`);
  return median;
}

const { cpuThrottlingRate, network } = CONDITIONS;
console.log(
  `計測条件: CPU ${cpuThrottlingRate}倍スロットリング / ${network.downloadKbps.toLocaleString('en-US')}kbps / RTT ${network.latencyMs}ms / 本番ビルド（各3回の中央値）`,
);

const bad = (await measurePage('s04-blocking')).LCP;
const good = (await measurePage('s04-optimized')).LCP;

if (bad === undefined || good === undefined) {
  check('両方のページで LCP が計測できている', false);
} else {
  check(`Bad 版の LCP が擬似タグの占有時間（${TAG_BLOCKING_MS}ms）以上`, bad >= TAG_BLOCKING_MS, ms(bad));
  const ratio = good / bad;
  check('改善版の LCP 中央値が Bad 版の 0.7 倍以下', ratio <= 0.7, `${ratio.toFixed(2)} 倍`);
}

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS04 の LCP 比較の検証に成功しました。');
