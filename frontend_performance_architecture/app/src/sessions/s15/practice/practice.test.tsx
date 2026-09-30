import type { ComponentType } from 'react';
import { renderToStaticMarkup, renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ProductList } from '../../../components/ProductList';
import { countRole, textOf, textsOf } from '../visible';
import { ProductListRestyled } from './ProductListRestyled';

// 問題2：同じテストが、書き方の違う2つの実装の両方で通ることを確かめる
const implementations: [string, ComponentType<{ keyword: string }>][] = [
  ['ProductList（出発点）', ProductList],
  ['ProductListRestyled（書き方だけ変えた版）', ProductListRestyled],
];

for (const [label, List] of implementations) {
  describe(label, () => {
    const html = renderToStaticMarkup(<List keyword="商品10" />);

    it('見出しに件数が出る', () => {
      expect(textsOf(html, 'heading')).toEqual(['商品一覧（111 件）']);
    });

    it('行の数が件数と一致する', () => {
      expect(countRole(html, 'listitem')).toBe(111);
    });

    it('先頭の行に名前・価格・カテゴリが見える', () => {
      expect(textsOf(html, 'listitem')[0]).toBe('商品10 470 円 雑貨');
    });

    it('空のキーワードでは全件', () => {
      expect(textOf(renderToStaticMarkup(<List keyword="" />))).toContain('商品一覧（2000 件）');
    });
  });
}

// Bad のテストが何に依存していたかを確かめる（書き方を変えた版では成り立たない）
describe('実装詳細に依存した検査は、見た目が同じでも壊れる', () => {
  const restyled = renderToString(<ProductListRestyled keyword="商品10" />);

  it('インライン style は書き方を変えた版には無い', () => {
    expect(restyled).not.toContain('<span style="width:120px">商品10</span>');
  });

  it('React が挟む <!-- --> の位置も書き方で変わる', () => {
    expect(restyled).not.toContain('商品一覧（<!-- -->111<!-- --> 件）');
    expect(renderToString(<ProductList keyword="商品10" />)).toContain('商品一覧（<!-- -->111<!-- --> 件）');
  });
});
