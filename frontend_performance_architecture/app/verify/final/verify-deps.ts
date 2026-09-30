import { join } from 'node:path';
import { formatViolation } from '../../src/sessions/s14/depRules.ts';
import { checkTarget, loadSources } from '../session14/check-deps.ts';
import { FINAL } from './check-deps.ts';

/**
 * 最終プロジェクト：模範解答版（src/sessions/final/done/）の構成と依存ルールの自己検証。
 * 実行: docker compose exec app node verify/final/verify-deps.ts
 * ファイル構成と違反の一覧は決定的なので、すべて完全一致で判定する。
 */
const failures: string[] = [];

function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

function sameLines(name: string, actual: string[], expected: string[]): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  check(name, ok, `${actual.length} 件`);
  if (!ok) {
    console.log('  期待:');
    for (const line of expected) console.log(`    ${line}`);
    console.log('  実際:');
    for (const line of actual) console.log(`    ${line}`);
  }
}

const done = loadSources(join(FINAL, 'done'));

sameLines('模範解答版のファイル構成（app・features・shared）', [...done.keys()].sort(), [
  'app/CatalogApp.tsx',
  'app/main.tsx',
  'features/campaign/CampaignBanner.tsx',
  'features/campaign/index.ts',
  'features/catalog/Catalog.tsx',
  'features/catalog/CatalogList.tsx',
  'features/catalog/SearchBox.tsx',
  'features/catalog/catalogView.ts',
  'features/catalog/index.ts',
  'features/chart/ChartToggle.tsx',
  'features/chart/index.ts',
  'features/print/PrintPreview.tsx',
  'features/print/index.ts',
  'features/print/loadPrintRenderer.ts',
  'shared/ui/styles.ts',
]);
sameLines('模範解答版は依存ルールの違反 0 件', checkTarget('featured', done).map(formatViolation), []);

// 規則違反を新しく書いたら検出できるか。ファイルは書き換えず、メモリ上で1行足して確かめる
function inject(path: string, line: string): string[] {
  const sources = new Map(done);
  sources.set(path, `${line}\n${done.get(path) ?? ''}`);
  return checkTarget('featured', sources).map(formatViolation);
}

sameLines(
  'catalog から print の内部を直接 import すると 1 件検出される',
  inject('features/catalog/Catalog.tsx', "import { loadPrintRenderer } from '../print/loadPrintRenderer';"),
  [
    '[cross-feature] features/catalog/Catalog.tsx → features/print/loadPrintRenderer.ts — features/catalog から features/print を直接 import しています（feature 同士の受け渡しは app で行います）',
  ],
);
sameLines(
  'shared/ui から features を import すると 1 件検出される',
  inject('shared/ui/styles.ts', "import { Catalog } from '../../features/catalog';"),
  [
    '[layer] shared/ui/styles.ts → features/catalog/index.ts — shared/ui から features/catalog へは依存できません（下の層から上の層への依存）',
  ],
);
sameLines(
  'app が公開窓口を通らずに import すると 1 件検出される',
  inject('app/CatalogApp.tsx', "import { PrintPreview } from '../features/print/PrintPreview';"),
  ['[public-api] app/CatalogApp.tsx → features/print/PrintPreview.tsx — features/print の公開窓口（index.ts）以外を import しています'],
);

// 出題版（1 ファイルにすべて）は、どの層にも属さない
const start = loadSources(join(FINAL, 'start'));
sameLines('出題版は app・features・shared のどこにも属さない（2 ファイルとも unplaced）', checkTarget('featured', start).map(formatViolation), [
  '[unplaced] StartCatalog.tsx — app・features・shared のどこにも属さない場所にあります',
  '[unplaced] main.tsx — app・features・shared のどこにも属さない場所にあります',
]);

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\n最終プロジェクトの構成と依存ルールの検証に成功しました。');
