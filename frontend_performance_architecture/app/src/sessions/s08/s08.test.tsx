import { renderToString } from 'react-dom/server';
import { beforeEach, describe, expect, it } from 'vitest';
import { products } from '../../data/products';
import { CatalogBad } from './CatalogBad';
import { CatalogMemo } from './CatalogMemo';
import { makeProducts } from './makeProducts';
import { PRODUCTS_20K } from './products20k';
import { countRender, readRenderCount, resetRenderCount } from './renderCount';

beforeEach(() => resetRenderCount());

const liCount = (html: string): number => html.match(/<li /g)?.length ?? 0;

describe('makeProducts', () => {
  it('2,000 件なら出発点の products と完全に一致する（同じ生成式）', () => {
    expect(makeProducts(2000)).toEqual(products);
  });

  it('20,000 件の先頭 2,000 件も出発点と一致する', () => {
    expect(PRODUCTS_20K).toHaveLength(20_000);
    expect(PRODUCTS_20K.slice(0, 2000)).toEqual(products);
  });

  it('「商品1」で絞り込むと 2,000 件中 1,111 件・20,000 件中 11,111 件が残る', () => {
    expect(products.filter((p) => p.name.includes('商品1'))).toHaveLength(1_111);
    expect(PRODUCTS_20K.filter((p) => p.name.includes('商品1'))).toHaveLength(11_111);
  });
});

describe('手動カウンタ', () => {
  it('名前ごとに回数を数え、reset で 0 に戻る', () => {
    countRender('row');
    countRender('row');
    countRender('list');
    expect(readRenderCount('row')).toBe(2);
    expect(readRenderCount('list')).toBe(1);
    resetRenderCount();
    expect(readRenderCount('row')).toBe(0);
  });

  it('初回のレンダリングでは、Bad 版もメモ化版も全行を1回ずつ実行する（memo は初回を省けない）', () => {
    const five = makeProducts(5);
    const badHtml = renderToString(<CatalogBad title="t" products={five} />);
    expect(readRenderCount('row')).toBe(5);
    resetRenderCount();
    const memoHtml = renderToString(<CatalogMemo title="t" products={five} />);
    expect(readRenderCount('row')).toBe(5);
    expect(liCount(badHtml)).toBe(5);
    expect(liCount(memoHtml)).toBe(5);
    // セレクタの契約：#keyword と section ul li
    expect(badHtml).toContain('id="keyword"');
    expect(badHtml).toMatch(/<section>.*<ul[^>]*>.*<li /s);
  });
});
