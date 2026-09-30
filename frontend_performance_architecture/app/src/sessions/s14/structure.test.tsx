import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { products } from '../../data/products';
import {
  checkDependencies,
  extractSpecifiers,
  judge,
  placeByDirectory,
  placeByPlan,
  resolveRelative,
  type Placement,
} from './depRules';
import { CatalogApp } from './featured/app/CatalogApp';
import { addItem, type CartLine } from './featured/features/cart/cartModel';
import { CartSummary } from './featured/features/cart/CartSummary';
import { ProductCatalog } from './featured/features/catalog/ProductCatalog';
import { App as FlatApp } from './flat/App';
import { CartSummary as FlatCartSummary } from './flat/components/CartSummary';
import { ProductCatalog as FlatProductCatalog } from './flat/components/ProductCatalog';
import { addItem as flatAddItem, type CartLine as FlatCartLine } from './flat/utils/cart';

const count = (html: string, pattern: RegExp) => (html.match(pattern) ?? []).length;
const noop = () => {};
const [p1, p2] = products;
if (!p1 || !p2) throw new Error('商品データが足りません');

describe('構成を変えても画面は変わらない', () => {
  it('画面全体の HTML が1文字も変わらない', () => {
    expect(renderToStaticMarkup(<CatalogApp />)).toBe(renderToStaticMarkup(<FlatApp />));
  });

  it('全件で 2000 行、「商品10」で 111 行（両方の構成で同じ）', () => {
    const good = renderToStaticMarkup(<ProductCatalog items={products} onAdd={noop} initialKeyword="商品10" />);
    const bad = renderToStaticMarkup(
      <FlatProductCatalog items={products} lines={[]} setLines={noop} initialKeyword="商品10" />,
    );
    expect(good).toBe(bad);
    expect(count(good, /<li /g)).toBe(111);
    expect(count(renderToStaticMarkup(<CatalogApp />), /<li /g)).toBe(2000);
  });

  it('同じ商品を2回・別の商品を1回入れると「3 点／合計 448 円」', () => {
    const good: CartLine[] = addItem(addItem(addItem([], p1), p2), p1);
    const bad: FlatCartLine[] = flatAddItem(flatAddItem(flatAddItem([], p1), p2), p1);
    const html = renderToStaticMarkup(<CartSummary lines={good} />);
    expect(html).toBe(renderToStaticMarkup(<FlatCartSummary lines={bad} />));
    expect(html).toContain('カート：3 点／合計 448 円');
  });

  it('feature 構成のカートは、渡された商品の余分な項目を写さない', () => {
    expect(addItem([], p1)).toStrictEqual([{ id: 1, name: '商品1', price: 137, quantity: 1 }]);
    expect(flatAddItem([], p1)[0]).toHaveProperty('category');
  });
});

describe('import の読み取り', () => {
  it('名前付き・型・export from・副作用・動的 import を拾い、コメントは無視する', () => {
    const source = [
      "import { useState } from 'react';",
      "import type { CartLine } from './cartModel';",
      'import {',
      '  formatYen,',
      "} from '../../shared/lib/format';",
      "export { CartSummary } from './CartSummary';",
      "export * from './types';",
      "import './styles.css';",
      "const Cart = lazy(() => import('../features/cart'));",
      "// import { old } from './old';",
      "/* import { older } from './older'; */",
    ].join('\n');
    expect(extractSpecifiers(source).sort()).toEqual(
      ['../../shared/lib/format', '../features/cart', './CartSummary', './cartModel', './styles.css', './types', 'react'].sort(),
    );
  });

  it('相対パスをファイルに解決する（拡張子と index を補う・範囲外とパッケージは null）', () => {
    const files = new Set(['app/CatalogApp.tsx', 'features/cart/index.ts', 'features/cart/cartModel.ts']);
    expect(resolveRelative('app/CatalogApp.tsx', '../features/cart', files)).toBe('features/cart/index.ts');
    expect(resolveRelative('features/cart/index.ts', './cartModel', files)).toBe('features/cart/cartModel.ts');
    expect(resolveRelative('features/cart/cartModel.ts', '.', files)).toBe('features/cart/index.ts');
    expect(resolveRelative('app/CatalogApp.tsx', '../../../../data/products', files)).toBeNull();
    expect(resolveRelative('app/CatalogApp.tsx', 'react', files)).toBeNull();
  });
});

describe('置き場所と規則の判定', () => {
  it('ディレクトリから層を決める', () => {
    expect(placeByDirectory('app/main.tsx')).toEqual({ layer: 'app', isPublic: false });
    expect(placeByDirectory('features/cart/index.ts')).toEqual({ layer: 'feature', feature: 'cart', isPublic: true });
    expect(placeByDirectory('features/cart/parts/index.ts')).toEqual({ layer: 'feature', feature: 'cart', isPublic: false });
    expect(placeByDirectory('shared/ui/Button.tsx')).toEqual({ layer: 'shared-ui', isPublic: false });
    expect(placeByDirectory('components/Button.tsx')).toBeNull();
  });

  it('移行計画の表から層を決める（移行先に置いたと仮定する）', () => {
    const place = placeByPlan({ 'utils/cart.ts': 'features/cart' });
    expect(place('utils/cart.ts')).toEqual({ layer: 'feature', feature: 'cart', isPublic: false });
    expect(place('utils/unknown.ts')).toBeNull();
  });

  // 練習問題2の (A)〜(G)
  const rule = (from: string, to: string) => {
    const a = placeByDirectory(from) as Placement;
    const b = placeByDirectory(to) as Placement;
    return judge(a, b)?.rule ?? 'OK';
  };
  it.each([
    ['A', 'features/cart/CartSummary.tsx', 'shared/lib/format.ts', 'OK'],
    ['B', 'shared/ui/Button.tsx', 'features/cart/index.ts', 'layer'],
    ['C', 'app/CatalogApp.tsx', 'features/catalog/filterProducts.ts', 'public-api'],
    ['D', 'features/catalog/ProductCatalog.tsx', 'features/cart/index.ts', 'cross-feature'],
    ['E', 'shared/ui/Button.tsx', 'shared/lib/format.ts', 'OK'],
    ['F', 'shared/lib/format.ts', 'shared/ui/Button.tsx', 'layer'],
    ['G', 'features/cart/index.ts', 'features/cart/cartModel.ts', 'OK'],
  ])('(%s) %s → %s は %s', (_label, from, to, expected) => {
    expect(rule(from, to)).toBe(expected);
  });

  it('どの層にも属さないファイルは unplaced として1回だけ報告する', () => {
    const sources = new Map([
      ['app/main.tsx', "import { helper } from '../misc/helper';"],
      ['misc/helper.ts', 'export const helper = 1;'],
    ]);
    expect(checkDependencies(sources, placeByDirectory).map((v) => `${v.rule} ${v.from}`)).toEqual(['unplaced misc/helper.ts']);
  });
});
