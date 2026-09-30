import { join } from 'node:path';
import { formatViolation } from '../../src/sessions/s14/depRules.ts';
import { checkTarget, loadSources, S14 } from './check-deps.ts';

/**
 * S14：依存ルール検査の自己検証。
 * 実行: docker compose exec app node verify/session14/verify-deps.ts
 * feature 構成は違反 0 件、種類別の構成は期待した 5 件ちょうどが出ることを完全一致で確かめる。
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

const featured = loadSources(join(S14, 'featured'));
check('featured のファイル数', featured.size === 11, `${featured.size} ファイル`);
sameLines('featured（feature 単位の構成）は違反 0 件', checkTarget('featured', featured).map(formatViolation), []);

const flat = loadSources(join(S14, 'flat'));
check('flat のファイル数', flat.size === 8, `${flat.size} ファイル`);
sameLines('flat（種類別の構成）を移行計画に照らすと 5 件の違反', checkTarget('flat', flat).map(formatViolation), [
  '[public-api] App.tsx → components/CartSummary.tsx — features/cart の公開窓口（index.ts）以外を import しています',
  '[public-api] App.tsx → components/ProductCatalog.tsx — features/catalog の公開窓口（index.ts）以外を import しています',
  '[public-api] App.tsx → utils/cart.ts — features/cart の公開窓口（index.ts）以外を import しています',
  '[cross-feature] components/ProductCatalog.tsx → utils/cart.ts — features/catalog から features/cart を直接 import しています（feature 同士の受け渡しは app で行います）',
  '[layer] utils/format.ts → utils/cart.ts — shared/lib から features/cart へは依存できません（下の層から上の層への依存）',
]);

// 規則違反を新しく書いたら検出できるか。ファイルは書き換えず、メモリ上で1行足して確かめる
const target = 'features/catalog/ProductCatalog.tsx';
const injected = new Map(featured);
injected.set(target, `import { addItem } from '../cart/cartModel';\n${featured.get(target) ?? ''}`);
sameLines('catalog から cart の内部を import すると 1 件検出される', checkTarget('featured', injected).map(formatViolation), [
  '[cross-feature] features/catalog/ProductCatalog.tsx → features/cart/cartModel.ts — features/catalog から features/cart を直接 import しています（feature 同士の受け渡しは app で行います）',
]);

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS14 の依存ルール検査の検証に成功しました。');
