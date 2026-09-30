import { readdirSync, readFileSync } from 'node:fs';
import { join, relative, resolve, sep } from 'node:path';
import {
  checkDependencies,
  formatViolation,
  placeByDirectory,
  placeByPlan,
  type Violation,
} from '../../src/sessions/s14/depRules.ts';

/**
 * S14：依存ルールの検査。import 文を読み取り、規則に反するものを一覧にする。
 * 実行: docker compose exec app node verify/session14/check-deps.ts featured
 *       docker compose exec app node verify/session14/check-deps.ts flat
 * 違反が1件でもあれば終了コード 1 で終わる（CI にそのまま組み込める）。
 */
export const S14 = resolve(import.meta.dirname, '../../src/sessions/s14');

/**
 * 移行前の棚卸し：種類別に並べた flat/ の各ファイルを、feature 構成ならどこへ置くか。
 * この表を先に作ると、動かす前に「今の import のうち何本が新しい規則に反するか」を数えられる。
 */
export const FLAT_PLAN: Readonly<Record<string, string>> = {
  'App.tsx': 'app',
  'main.tsx': 'app',
  'components/Button.tsx': 'shared/ui',
  'components/ProductCatalog.tsx': 'features/catalog',
  'components/CartSummary.tsx': 'features/cart',
  'utils/filter.ts': 'features/catalog',
  'utils/cart.ts': 'features/cart',
  'utils/format.ts': 'shared/lib',
};

export type Target = 'featured' | 'flat';

/** ディレクトリ配下の .ts / .tsx を読み込む（テストは除く）。キーはルートからの相対パス（区切りは /） */
export function loadSources(root: string): Map<string, string> {
  const sources = new Map<string, string>();
  for (const entry of readdirSync(root, { recursive: true, withFileTypes: true })) {
    if (!entry.isFile() || !/\.tsx?$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) continue;
    const full = join(entry.parentPath, entry.name);
    sources.set(relative(root, full).split(sep).join('/'), readFileSync(full, 'utf8'));
  }
  return sources;
}

export function checkTarget(target: Target, sources: ReadonlyMap<string, string>): Violation[] {
  const place = target === 'featured' ? placeByDirectory : placeByPlan(FLAT_PLAN);
  return checkDependencies(sources, place);
}

// 直接実行されたときだけ結果を表示する（verify-deps.ts から import されたときは何もしない）
if (resolve(process.argv[1] ?? '') === import.meta.filename) {
  const target = process.argv[2] ?? 'featured';
  if (target !== 'featured' && target !== 'flat') {
    console.error('使い方: node verify/session14/check-deps.ts <featured|flat>');
    process.exit(2);
  }
  const sources = loadSources(join(S14, target));
  const violations = checkTarget(target, sources);
  console.log(`対象: src/sessions/s14/${target}/（${sources.size} ファイル）`);
  for (const v of violations) console.log(formatViolation(v));
  console.log(`違反 ${violations.length} 件`);
  process.exit(violations.length > 0 ? 1 : 0);
}
