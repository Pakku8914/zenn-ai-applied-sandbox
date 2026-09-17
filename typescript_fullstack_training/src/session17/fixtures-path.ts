// セッション17「非同期処理」で使う fixtures のパス解決。
//
// カレントディレクトリがどこであっても同じファイルを指せるように、
// 「このファイルの位置」を基準にして絶対パスを組み立てる。

import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

// import.meta.url は自分自身の URL（file:// で始まる）。
// fileURLToPath で通常のパスに変換し、dirname でディレクトリを取り出す。
const here = dirname(fileURLToPath(import.meta.url));

/** sandbox の fixtures フォルダにあるファイルの絶対パスを返す */
export function fixturePath(fileName: string): string {
  return join(here, '..', '..', 'fixtures', fileName);
}
