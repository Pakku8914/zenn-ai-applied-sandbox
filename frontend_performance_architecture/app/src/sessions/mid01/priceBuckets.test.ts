import { describe, expect, it } from 'vitest';
import { products } from '../../data/products';
import { BUCKET_COUNT, priceBuckets } from './priceBuckets';

describe('priceBuckets', () => {
  it('2,000 件を 10 本の価格帯に漏れなく振り分ける', () => {
    const counts = priceBuckets(products);
    expect(counts).toHaveLength(BUCKET_COUNT);
    expect(counts.reduce((a, b) => a + b, 0)).toBe(2_000);
  });

  it('どの価格帯にも商品がある（空の棒を描かない）', () => {
    expect(priceBuckets(products).every((c) => c > 0)).toBe(true);
  });

  it('端の価格（100 円・9,999 円）を最初と最後の棒に入れる', () => {
    const edge = [
      { id: 1, name: '安い', price: 100, category: '文具' },
      { id: 2, name: '高い', price: 9_999, category: '文具' },
    ];
    expect(priceBuckets(edge)).toEqual([1, 0, 0, 0, 0, 0, 0, 0, 0, 1]);
  });
});
