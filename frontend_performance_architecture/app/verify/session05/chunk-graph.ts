import { basename } from 'node:path';
import { bytesOf, fmt, reachableFiles, type Chunk } from './bundle-stats.ts';

/**
 * 練習問題7の解答。入口から届くチャンクの関係を Mermaid の flowchart にする。
 * 静的 import は実線（最初の読み込みで一緒に取得）、動的 import() は点線（あとで取得）。
 */
export function chunkGraphMermaid(chunks: Map<string, Chunk>, entry: Chunk, outDir: string): string {
  const files = reachableFiles(chunks, entry).sort();
  const idOf = (file: string): string => `c${files.indexOf(file)}`;
  // ハッシュ付きのファイル名から、読みやすいチャンク名（例: HeavyChart）だけを残す
  const label = (file: string): string => basename(file).replace(/-[\w-]{8}\.js$/, '');

  const lines = ['flowchart TD'];
  for (const file of files) {
    lines.push(`  ${idOf(file)}["${label(file)}<br/>${fmt(bytesOf(outDir, [file]))} B"]`);
  }
  for (const file of files) {
    const chunk = chunks.get(file);
    if (!chunk) continue;
    for (const to of chunk.imports) lines.push(`  ${idOf(file)} --> ${idOf(to)}`);
    for (const to of chunk.dynamicImports) lines.push(`  ${idOf(file)} -.-> ${idOf(to)}`);
  }
  return lines.join('\n');
}
