import { buildApp, entryOf } from './bundle-stats.ts';
import { chunkGraphMermaid } from './chunk-graph.ts';

/**
 * 練習問題7：ページのチャンク依存グラフを Mermaid で出力する。
 * 実行: docker compose exec app node verify/session05/graph.ts s05-lazy-chart
 */
const page = process.argv[2] ?? 'main';
const OUT = '/tmp/s05-graph-dist';

const chunks = await buildApp(OUT);
console.log(chunkGraphMermaid(chunks, entryOf(chunks, page), OUT));
