import { renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { makeProducts } from '../../s08/makeProducts';
import { ReviewCatalogFixed } from './ReviewCatalogFixed';

const liCount = (html: string): number => html.match(/<li /g)?.length ?? 0;

describe('問題7：ReviewCatalogFixed', () => {
  it('20,000 件でも最初に出力する行は 15 行', () => {
    expect(liCount(renderToString(<ReviewCatalogFixed products={makeProducts(20_000)} />))).toBe(15);
  });

  it('価格の安い順に並ぶ（2,000 件で最安は 101 円の商品1873）', () => {
    const html = renderToString(<ReviewCatalogFixed products={makeProducts(2000)} />);
    expect(html.indexOf('商品1873')).toBeGreaterThan(-1);
    expect(html.indexOf('商品1873')).toBeLessThan(html.indexOf('</li>'));
  });

  it('元の配列（props）は並び替えで書き換わらない', () => {
    const products = makeProducts(2000);
    renderToString(<ReviewCatalogFixed products={products} />);
    expect(products[0]?.id).toBe(1);
  });
});
