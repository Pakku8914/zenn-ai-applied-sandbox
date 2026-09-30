import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { gzipSync } from 'node:zlib';
import {
  buildApp,
  bytesOf,
  containsModule,
  entryOf,
  fmt,
  initialFiles,
  reachableFiles,
  type Chunk,
} from './bundle-stats.ts';
import { chunkGraphMermaid } from './chunk-graph.ts';

/**
 * S05 のビルド成果物を調べ、分割の結果が本文どおりになっていることを確かめる。
 * 実行: docker compose exec app node verify/session05/verify-bundle.ts
 * バイト数・チャンク数は決定的なので、大小関係や包含で判定する。
 */
const OUT = '/tmp/s05-verify-dist';
const failures: string[] = [];

function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

const chunks = await buildApp(OUT);
const page = (name: string): { entry: Chunk; initial: string[]; reachable: string[]; bytes: number } => {
  const entry = entryOf(chunks, name);
  const initial = initialFiles(chunks, entry);
  return { entry, initial, reachable: reachableFiles(chunks, entry), bytes: bytesOf(OUT, initial) };
};
const signed = (n: number): string => `${n >= 0 ? '+' : ''}${fmt(n)}`;

const HEAVY_CHART = /\/src\/components\/HeavyChart\.tsx$/;
const REACT_DOM_SERVER = /react-dom-server/;

const main = page('main');
const lazyChart = page('s05-lazy-chart');
const eager = page('s05-print-eager');
const lazyPrint = page('s05-print-lazy');
const handmade = page('s05-print-handmade');
const prefetch = page('s05-print-prefetch');
const overSplit = page('s05-over-split');

console.log('ページ別の初期 JS（入口から静的 import でたどれるファイルの合計）');
for (const [name, p] of Object.entries({ main, 's05-lazy-chart': lazyChart, 's05-print-eager': eager, 's05-print-lazy': lazyPrint, 's05-print-handmade': handmade, 's05-over-split': overSplit })) {
  console.log(`  ${name.padEnd(18)} ${String(p.initial.length).padStart(2)} ファイル  ${fmt(p.bytes).padStart(9)} バイト`);
}
console.log('');

// 1. HeavyChart の遅延読み込み
check('出発点: HeavyChart が初期 JS に含まれる', containsModule(chunks, main.initial, HEAVY_CHART));
check('s05-lazy-chart: HeavyChart が初期 JS に含まれない', !containsModule(chunks, lazyChart.initial, HEAVY_CHART));
check('s05-lazy-chart: HeavyChart は動的 import の先にある', containsModule(chunks, lazyChart.reachable, HEAVY_CHART));
const chartDiff = lazyChart.bytes - main.bytes;
// HeavyChart は小さいので差もわずか。向きは分割の補助コードとの兼ね合いで決まる
check('s05-lazy-chart と出発点の初期 JS の差は 5,000 バイト未満', Math.abs(chartDiff) < 5_000, `${signed(chartDiff)} バイト`);

// 2. 大きな依存（react-dom/server）の遅延読み込み
check('s05-print-eager: react-dom/server が初期 JS に含まれる', containsModule(chunks, eager.initial, REACT_DOM_SERVER));
check('s05-print-lazy: react-dom/server が初期 JS に含まれない', !containsModule(chunks, lazyPrint.initial, REACT_DOM_SERVER));
check('s05-print-lazy: react-dom/server は動的 import の先にある', containsModule(chunks, lazyPrint.reachable, REACT_DOM_SERVER));
const printDiff = eager.bytes - lazyPrint.bytes;
check('s05-print-eager の初期 JS が s05-print-lazy より 30,000 バイト以上多い', printDiff >= 30_000, `${signed(printDiff)} バイト`);
check('s05-print-prefetch（練習問題4）: react-dom/server が初期 JS に含まれない', !containsModule(chunks, prefetch.initial, REACT_DOM_SERVER));

// 3. 依存を減らした版
check('s05-print-handmade: react-dom/server がどこにも含まれない', !containsModule(chunks, handmade.reachable, REACT_DOM_SERVER));
const handmadeAll = bytesOf(OUT, handmade.reachable);
const lazyAll = bytesOf(OUT, lazyPrint.reachable);
check('s05-print-handmade の取得しうる JS が s05-print-lazy より少ない', handmadeAll < lazyAll, `${fmt(handmadeAll)} / ${fmt(lazyAll)} バイト`);

// 4. 分割しすぎ
const lazyChunks = overSplit.reachable.filter((f) => !overSplit.initial.includes(f));
check('s05-over-split: 動的 import の先のチャンクが 4 つ以上', lazyChunks.length >= 4, `${lazyChunks.length} 個`);
const bodies = lazyChunks.map((f) => readFileSync(join(OUT, f)));
const gzipEach = bodies.reduce((sum, b) => sum + gzipSync(b).length, 0);
const gzipJoined = gzipSync(Buffer.concat(bodies)).length;
check(
  's05-over-split: 別々に圧縮した合計が、まとめて圧縮したときより大きい',
  gzipEach > gzipJoined,
  `別々 ${fmt(gzipEach)} / まとめて ${fmt(gzipJoined)} バイト（gzip）`,
);

// 5. 練習問題7：チャンクの依存グラフ
const graph = chunkGraphMermaid(chunks, lazyChart.entry, OUT);
check('練習問題7: s05-lazy-chart のグラフに動的 import の点線がある', graph.startsWith('flowchart TD') && graph.includes('-.->'));

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS05 のビルド成果物の検証に成功しました。');
