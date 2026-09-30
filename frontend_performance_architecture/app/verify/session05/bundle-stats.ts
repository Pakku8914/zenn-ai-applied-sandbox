import { statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { build } from 'vite';

// app コンテナは NODE_ENV=development で動いている。build() の mode: 'production' だけでは
// React が開発版のままバンドルされる（初期 JS が約2倍になる）ため、環境変数も上書きする。
process.env.NODE_ENV = 'production';

/**
 * S05：vite の build() API が返すビルド結果（チャンクとモジュールの一覧）を集計する小さな道具。
 * 可視化ツールは追加せず、ビルドが返す情報だけで「何が大きいか」を調べる。
 */
export const ROOT = resolve(import.meta.dirname, '../..');

/** build() が返すチャンクのうち、本章で使う項目だけを書いた型 */
export type Chunk = {
  type: 'chunk';
  fileName: string;
  name: string;
  isEntry: boolean;
  imports: string[];
  dynamicImports: string[];
  modules: Record<string, { renderedLength: number }>;
  code: string;
};

/**
 * プロジェクトの vite.config.ts（全ページが入口）のまま本番ビルドし、チャンクを返す。
 * preview と同じ設定なので、ここで数えた初期 JS はブラウザで測る jsBytes と同じ構成になる。
 */
export async function buildApp(outDir: string): Promise<Map<string, Chunk>> {
  const result = await build({
    root: ROOT,
    // app コンテナは NODE_ENV=development。指定しないと React の開発版が入り約2倍に膨らむ
    mode: 'production',
    logLevel: 'silent',
    // dist/ は preview が配信中なので、/tmp/ 配下に出力する
    build: { outDir, emptyOutDir: true },
  });
  const outputs = Array.isArray(result) ? result : [result];
  const chunks = new Map<string, Chunk>();
  for (const out of outputs) {
    for (const item of out.output) {
      if (item.type === 'chunk') chunks.set(item.fileName, item as Chunk);
    }
  }
  return chunks;
}

/** 入口の名前（出発点は main、改善版はページのディレクトリ名）からチャンクを探す */
export function entryOf(chunks: Map<string, Chunk>, name: string): Chunk {
  const found = [...chunks.values()].find((c) => c.isEntry && c.name === name);
  if (!found) throw new Error(`入口 ${name} のチャンクが見つかりません`);
  return found;
}

function walk(chunks: Map<string, Chunk>, start: string, followDynamic: boolean): string[] {
  const seen = new Set<string>();
  const stack = [start];
  while (stack.length > 0) {
    const file = stack.pop()!;
    if (seen.has(file)) continue;
    seen.add(file);
    const chunk = chunks.get(file);
    if (!chunk) continue;
    stack.push(...chunk.imports);
    if (followDynamic) stack.push(...chunk.dynamicImports);
  }
  return [...seen];
}

/** 最初の読み込みで取得されるファイル＝入口から静的 import だけをたどった集合 */
export const initialFiles = (chunks: Map<string, Chunk>, entry: Chunk): string[] =>
  walk(chunks, entry.fileName, false);

/** いずれ取得されうるファイル＝動的 import() の先まで含めてたどった集合 */
export const reachableFiles = (chunks: Map<string, Chunk>, entry: Chunk): string[] =>
  walk(chunks, entry.fileName, true);

/** 出力ファイルの実際のバイト数の合計（ブラウザの decodedBodySize と同じもの） */
export const bytesOf = (outDir: string, files: string[]): number =>
  files.reduce((sum, file) => sum + statSync(join(outDir, file)).size, 0);

/** モジュール ID を読める形にする（node_modules はパッケージ以下、それ以外は app/ からの相対） */
export function displayId(id: string): string {
  const nm = id.lastIndexOf('/node_modules/');
  if (nm >= 0) return id.slice(nm + '/node_modules/'.length);
  if (!id.startsWith('/')) return `（ビルドが追加した補助コード）${id.replace(/\0/g, '')}`;
  return relative(ROOT, id);
}

/** モジュール ID をパッケージ単位にまとめる（@scope/name にも対応） */
export function packageOf(id: string): string {
  const nm = id.lastIndexOf('/node_modules/');
  if (nm < 0) return id.startsWith('/') ? '（自分のコード）' : '（ビルドが追加した補助コード）';
  const [first = '', second = ''] = id.slice(nm + '/node_modules/'.length).split('/');
  return first.startsWith('@') ? `${first}/${second}` : first;
}

export type SizeRow = { label: string; length: number; share: number };

/** 指定したファイル群に含まれるモジュールを、renderedLength の大きい順に集計する */
export function sizeBy(
  chunks: Map<string, Chunk>,
  files: string[],
  keyOf: (id: string) => string,
): SizeRow[] {
  const totals = new Map<string, number>();
  for (const file of files) {
    for (const [id, info] of Object.entries(chunks.get(file)?.modules ?? {})) {
      totals.set(keyOf(id), (totals.get(keyOf(id)) ?? 0) + info.renderedLength);
    }
  }
  const all = [...totals.values()].reduce((a, b) => a + b, 0);
  return [...totals.entries()]
    .map(([label, length]) => ({ label, length, share: all === 0 ? 0 : length / all }))
    .sort((a, b) => b.length - a.length);
}

/** 指定したファイル群のどれかに、ID が pattern に一致するモジュールが含まれるか */
export const containsModule = (chunks: Map<string, Chunk>, files: string[], pattern: RegExp): boolean =>
  files.some((file) => Object.keys(chunks.get(file)?.modules ?? {}).some((id) => pattern.test(id)));

export const fmt = (n: number): string => n.toLocaleString('en-US');
