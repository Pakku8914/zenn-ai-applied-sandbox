import { describe, expect, it } from 'vitest';
import { checkDependencies, formatViolation, placeByDirectory, placeByPlan } from './depRules';
import { judgeStrict } from './practice/selfImport';

// 練習問題7：移行の途中（動かしたファイルと、まだ動かしていないファイルが混ざった状態）を検査する
describe('移行途中の検査', () => {
  const plan = placeByPlan({ 'App.tsx': 'app', 'components/ProductCatalog.tsx': 'features/catalog' });
  const place = (path: string) => plan(path) ?? placeByDirectory(path);
  const sources = new Map([
    ['App.tsx', "import { CartSummary } from './features/cart';\nimport { ProductCatalog } from './components/ProductCatalog';"],
    ['components/ProductCatalog.tsx', "import { formatYen } from '../shared/lib/format';"],
    ['features/cart/index.ts', "export { CartSummary } from './CartSummary';"],
    ['features/cart/CartSummary.tsx', "import { formatYen } from '../../shared/lib/format';"],
    ['shared/lib/format.ts', 'export const formatYen = (n: number) => `${n} 円`;'],
  ]);

  it('計画の表に無いファイルはディレクトリで判定し、残りの違反だけが出る', () => {
    expect(checkDependencies(sources, place).map(formatViolation)).toEqual([
      '[public-api] App.tsx → components/ProductCatalog.tsx — features/catalog の公開窓口（index.ts）以外を import しています',
    ]);
  });
});

// 練習問題4：自分の公開窓口を import する内部ファイルを検出する
describe('self-public 規則', () => {
  const sources = new Map([
    ['app/CatalogApp.tsx', "import { CartSummary } from '../features/cart';"],
    ['features/cart/index.ts', "export { CartSummary } from './CartSummary';\nexport { useCart } from './useCart';"],
    ['features/cart/CartSummary.tsx', "import { useCart } from '.';"],
    ['features/cart/useCart.ts', "import { addItem } from './cartModel';"],
    ['features/cart/cartModel.ts', "import type { CartLine } from '../cart';"],
  ]);

  it('既定の規則では 0 件', () => {
    expect(checkDependencies(sources, placeByDirectory)).toEqual([]);
  });

  it('規則を足すと、index を経由して自分を読んでいる 2 件が出る（app と index 自身は対象外）', () => {
    expect(checkDependencies(sources, placeByDirectory, judgeStrict).map(formatViolation)).toEqual([
      '[self-public] features/cart/CartSummary.tsx → features/cart/index.ts — features/cart の内部から自分の公開窓口を import しています（循環 import の元）',
      '[self-public] features/cart/cartModel.ts → features/cart/index.ts — features/cart の内部から自分の公開窓口を import しています（循環 import の元）',
    ]);
  });

  it('既存の規則の判定は変えない', () => {
    const shared = placeByDirectory('shared/ui/Button.tsx');
    const cart = placeByDirectory('features/cart/index.ts');
    if (!shared || !cart) throw new Error('置き場所が決まりません');
    expect(judgeStrict(shared, cart)?.rule).toBe('layer');
  });
});
