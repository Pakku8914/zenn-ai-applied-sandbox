import { CONDITIONS } from '../vitals-client.ts';
import { measureLab, type LabResult, type Throttle } from './lab.ts';

/**
 * S03：計測条件（ビルド種別・CPU・ネットワーク）が結果を変えることを確かめる。
 * 時間の絶対値は環境で変わるため、判定はすべて大小関係で行う。
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const DEV = process.env.DEV_URL ?? 'http://app.test:5173';
const RUNS = 3;

const BOTH: Throttle = { cpu: true, network: true };
const NONE: Throttle = { cpu: false, network: false };

const cases = [
  { key: 'prodBoth', label: '本番ビルド / スロットリングあり', url: TARGET, throttle: BOTH },
  { key: 'prodNone', label: '本番ビルド / スロットリングなし', url: TARGET, throttle: NONE },
  { key: 'prodCpu', label: '本番ビルド / CPU のみ', url: TARGET, throttle: { cpu: true, network: false } },
  { key: 'prodNet', label: '本番ビルド / ネットワークのみ', url: TARGET, throttle: { cpu: false, network: true } },
  { key: 'devBoth', label: '開発サーバー / スロットリングあり', url: DEV, throttle: BOTH },
  { key: 'devNone', label: '開発サーバー / スロットリングなし', url: DEV, throttle: NONE },
] as const;

const failures: string[] = [];
function check(name: string, ok: boolean, detail: string): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name} — ${detail}`);
  if (!ok) failures.push(name);
}
const bytes = (n: number): string => n.toLocaleString('en-US');

console.log(
  `標準条件: CPU ${CONDITIONS.cpuThrottlingRate}x スロットリング / ${CONDITIONS.network.downloadKbps}kbps / ` +
    `RTT ${CONDITIONS.network.latencyMs}ms / 各 ${RUNS} 回の中央値`,
);
console.log('');

const r = {} as Record<(typeof cases)[number]['key'], LabResult>;
for (const c of cases) {
  r[c.key] = await measureLab(c.url, c.throttle, RUNS);
  console.log(
    `${c.label}  LCP ${r[c.key].lcp}ms  リクエスト ${r[c.key].requests}  JS ${bytes(r[c.key].jsBytes)} バイト`,
  );
}
console.log('');

check('本番ビルド: スロットリングありの LCP > なし', r.prodBoth.lcp > r.prodNone.lcp,
  `${r.prodBoth.lcp}ms > ${r.prodNone.lcp}ms`);
check('本番ビルド: CPU だけ絞っても LCP が伸びる', r.prodCpu.lcp > r.prodNone.lcp,
  `${r.prodCpu.lcp}ms > ${r.prodNone.lcp}ms`);
check('本番ビルド: ネットワークだけ絞っても LCP が伸びる', r.prodNet.lcp > r.prodNone.lcp,
  `${r.prodNet.lcp}ms > ${r.prodNone.lcp}ms`);
check('リクエスト数: 開発サーバー > 本番ビルド', r.devBoth.requests > r.prodBoth.requests,
  `${r.devBoth.requests} > ${r.prodBoth.requests}`);
check('JS 量: 開発サーバー > 本番ビルド', r.devBoth.jsBytes > r.prodBoth.jsBytes,
  `${bytes(r.devBoth.jsBytes)} > ${bytes(r.prodBoth.jsBytes)} バイト`);

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS03 条件比較の検証に成功しました。');
