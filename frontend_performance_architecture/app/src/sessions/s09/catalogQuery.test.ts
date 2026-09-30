import { describe, expect, it } from 'vitest';
import { products } from '../../data/products';
import {
  CATEGORY_ALL,
  DEFAULT_QUERY,
  MAX_KEYWORD_LENGTH,
  countInCategory,
  decideHistoryMode,
  filterProducts,
  parseCatalogQuery,
  toSearch,
  type CatalogQuery,
  type CategoryOption,
} from './catalogQuery';

describe('parseCatalogQuery', () => {
  it('空の検索部分は既定値になる', () => {
    expect(parseCatalogQuery('')).toEqual(DEFAULT_QUERY);
  });

  it('q と category を読む（パーセントエンコードも元に戻す）', () => {
    const search = `?q=${encodeURIComponent('商品10')}&category=${encodeURIComponent('書籍')}`;
    expect(parseCatalogQuery(search)).toEqual({ keyword: '商品10', category: '書籍' });
  });

  it('+ は空白として、%2B は + として読む', () => {
    expect(parseCatalogQuery('?q=a+b').keyword).toBe('a b');
    expect(parseCatalogQuery('?q=a%2Bb').keyword).toBe('a+b');
  });

  it('知らないカテゴリは「すべて」に戻す', () => {
    expect(parseCatalogQuery(`?category=${encodeURIComponent('家電')}`).category).toBe(CATEGORY_ALL);
  });

  it('長すぎるキーワードは上限で切る', () => {
    expect(parseCatalogQuery(`?q=${'あ'.repeat(150)}`).keyword).toHaveLength(MAX_KEYWORD_LENGTH);
  });
});

describe('toSearch', () => {
  it('既定値だけなら空文字（? も付けない）', () => {
    expect(toSearch(DEFAULT_QUERY)).toBe('');
  });

  it('キーの順序が固定なので、同じ状態は同じ URL になる', () => {
    expect(toSearch({ keyword: 'x', category: '書籍' })).toBe(`?q=x&category=${encodeURIComponent('書籍')}`);
  });

  it('空白は + になり、読み戻すと空白に戻る', () => {
    const search = toSearch({ keyword: '赤 ペン', category: CATEGORY_ALL });
    expect(search).toContain('+');
    expect(parseCatalogQuery(search).keyword).toBe('赤 ペン');
  });

  const samples: CatalogQuery[] = [
    DEFAULT_QUERY,
    { keyword: '商品10', category: CATEGORY_ALL },
    { keyword: '', category: '食品' },
    { keyword: 'a&b=c#d+e', category: '雑貨' },
  ];
  it.each(samples)('状態 → URL → 状態 で元に戻る（%o）', (query) => {
    expect(parseCatalogQuery(toSearch(query))).toEqual(query);
  });
});

describe('filterProducts（件数は決定的なので完全一致で確かめる）', () => {
  const cases: [string, CategoryOption, number][] = [
    ['', CATEGORY_ALL, 2000],
    ['商品10', CATEGORY_ALL, 111],
    ['商品1', CATEGORY_ALL, 1111],
    ['', '書籍', 500],
    ['商品10', '文具', 28],
    ['商品10', '書籍', 28],
    ['商品10', '雑貨', 28],
    ['商品10', '食品', 27],
  ];
  it.each(cases)('keyword=%s category=%s → %i 件', (keyword, category, expected) => {
    expect(filterProducts(products, { keyword, category })).toHaveLength(expected);
  });
});

describe('countInCategory', () => {
  it('商品1・商品5 は書籍、商品2 は雑貨', () => {
    expect(countInCategory([2, 1, 5], '書籍', products)).toBe(2);
  });
});

describe('decideHistoryMode', () => {
  it('入力の最初の1文字は積み、続きは置き換える', () => {
    expect(decideHistoryMode(false, 'typing')).toBe('push');
    expect(decideHistoryMode(true, 'typing')).toBe('replace');
  });

  it('確定操作は入力の途中でも積む', () => {
    expect(decideHistoryMode(false, 'commit')).toBe('push');
    expect(decideHistoryMode(true, 'commit')).toBe('push');
  });
});
