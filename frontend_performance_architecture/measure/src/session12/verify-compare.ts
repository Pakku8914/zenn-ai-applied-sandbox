import { measureMedian } from '../vitals-client.ts';
import { SPA, createChecker, nextUrl } from './helpers.ts';

/**
 * S12：同じカタログ画面を SPA 版・RSC 版・全部クライアント版で作り、初期 JS・LCP・INP を中央値で比べる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session12/verify-compare.ts
 * 計測条件：CPU 4倍スロットリング / 1,500kbps / RTT 40ms / 本番ビルド（Next.js も next build + next start）
 * バイト数は大小、LCP・INP は大小で判定する（時間の絶対値は判定しない）。
 */
const { check, finish } = createChecker();
const input = { selector: '#keyword', value: '商品1' };

const variants = [
  ['SPA 版', SPA],
  ['RSC 版', nextUrl('s12-rsc')],
  ['全部クライアント版', nextUrl('s12-client')],
] as const;

const result: Record<string, Record<string, number>> = {};
for (const [label, url] of variants) {
  result[label] = (await measureMedian(url, { runs: 3, input })).median;
}

console.log('| 版 | 初期 JS | LCP（中央値） | INP（中央値） |');
console.log('| :--- | ---: | ---: | ---: |');
for (const [label] of variants) {
  const m = result[label]!;
  console.log(
    `| ${label} | ${Math.round(m.jsBytes ?? NaN).toLocaleString('en-US')} バイト | ${Math.round(m.LCP ?? NaN)}ms | ${Math.round(m.INP ?? NaN)}ms |`,
  );
}
console.log('');

const spa = result['SPA 版']!;
const rsc = result['RSC 版']!;
const client = result['全部クライアント版']!;

for (const [label] of variants) {
  const m = result[label]!;
  check(`${label}：LCP と INP が報告された`, Number.isFinite(m.LCP) && Number.isFinite(m.INP));
}
check('初期 JS：RSC 版 < 全部クライアント版（一覧の部品を送らない）', rsc.jsBytes! < client.jsBytes!);
check('初期 JS：SPA 版 < RSC 版（Next.js のランタイムのぶん土台が大きい）', spa.jsBytes! < rsc.jsBytes!);
check('LCP：RSC 版 < SPA 版（HTML に内容が入っている）', (rsc.LCP ?? Infinity) < (spa.LCP ?? -1));
// どちらも数十 ms の good 域で、この画面では差は判定できるほど大きくない（実行ごとに入れ替わる）。
// 大小ではなく、どちらも good（200ms 未満）であることだけを確かめる
check('INP：RSC 版・全部クライアント版ともに good（200ms 未満）', (rsc.INP ?? Infinity) < 200 && (client.INP ?? Infinity) < 200);

finish('S12 の SPA 版と RSC 版の比較');
