import { join, resolve } from 'node:path';
import { formatViolation } from '../../src/sessions/s14/depRules.ts';
import { checkTarget, loadSources } from '../session14/check-deps.ts';

/**
 * 最終プロジェクト：src/sessions/final/<ディレクトリ>/ を、S14 と同じ依存ルール（feature 構成）で検査する。
 * 実行: docker compose exec app node verify/final/check-deps.ts done
 *       docker compose exec app node verify/final/check-deps.ts mine   ← 自分の改善版
 * 違反が1件でもあれば終了コード 1 で終わる（CI にそのまま組み込める）。
 */
export const FINAL = resolve(import.meta.dirname, '../../src/sessions/final');

/** 外から渡る名前なので、ディレクトリ名として安全な文字だけを受け付ける */
const DIR_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;

if (resolve(process.argv[1] ?? '') === import.meta.filename) {
  const dir = process.argv[2] ?? 'done';
  if (!DIR_PATTERN.test(dir)) {
    console.error('使い方: node verify/final/check-deps.ts <src/sessions/final の下のディレクトリ名（英小文字・数字・ハイフン）>');
    process.exit(2);
  }
  const sources = loadSources(join(FINAL, dir));
  const violations = checkTarget('featured', sources);
  console.log(`対象: src/sessions/final/${dir}/（${sources.size} ファイル）`);
  for (const v of violations) console.log(formatViolation(v));
  console.log(`違反 ${violations.length} 件`);
  process.exit(violations.length > 0 ? 1 : 0);
}
