import { describe, expect, it } from 'vitest';
import { products } from '../../../data/products';
import { CATEGORY_ALL } from '../catalogQuery';
import { summarizeCart } from './cartSummary';
import { parseSortedQuery, sortProducts, toSortedSearch, type SortedCatalogQuery } from './sortQuery';

describe('練習問題2：並び順を URL に置く', () => {
  it('sort を読む。知らない値は既定の id 順に戻す', () => {
    expect(parseSortedQuery('?sort=price-asc').sort).toBe('price-asc');
    expect(parseSortedQuery('?sort=cheap').sort).toBe('id');
    expect(parseSortedQuery('').sort).toBe('id');
  });

  it('既定値は URL に書かない', () => {
    expect(toSortedSearch({ keyword: '', category: CATEGORY_ALL, sort: 'id' })).toBe('');
  });

  it('q → category → sort の順に並ぶ', () => {
    expect(toSortedSearch({ keyword: 'x', category: '書籍', sort: 'price-desc' })).toBe(
      `?q=x&category=${encodeURIComponent('書籍')}&sort=price-desc`,
    );
  });

  const samples: SortedCatalogQuery[] = [
    { keyword: '', category: CATEGORY_ALL, sort: 'id' },
    { keyword: '商品10', category: '食品', sort: 'price-asc' },
    { keyword: 'a b', category: CATEGORY_ALL, sort: 'price-desc' },
  ];
  it.each(samples)('状態 → URL → 状態 で元に戻る（%o）', (query) => {
    expect(parseSortedQuery(toSortedSearch(query))).toEqual(query);
  });

  it('価格の安い順・高い順の先頭（価格はすべて異なる）', () => {
    const asc = sortProducts(products, 'price-asc');
    const desc = sortProducts(products, 'price-desc');
    expect(asc[0]).toMatchObject({ name: '商品1873', price: 101 });
    expect(desc[0]).toMatchObject({ name: '商品535', price: 9995 });
  });

  it('元の配列は並べ替えない', () => {
    sortProducts(products, 'price-desc');
    expect(products[0]?.name).toBe('商品1');
  });
});

describe('練習問題3：カートの集計を計算で出す', () => {
  it('点数と合計金額（商品1〜3 は 137・174・211 円）', () => {
    expect(summarizeCart([1, 2, 3], products)).toEqual({ count: 3, totalPrice: 522 });
  });

  it('同じ商品を2回入れたら2点', () => {
    expect(summarizeCart([1, 1], products)).toEqual({ count: 2, totalPrice: 274 });
  });

  it('存在しない商品は点数にも金額にも数えない', () => {
    expect(summarizeCart([9999], products)).toEqual({ count: 0, totalPrice: 0 });
  });
});
