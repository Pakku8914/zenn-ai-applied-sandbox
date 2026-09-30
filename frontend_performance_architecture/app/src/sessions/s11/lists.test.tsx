import { renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { makeProducts } from '../s08/makeProducts';
import { PlainProductList } from './PlainProductList';
import { VirtualProductList } from './VirtualProductList';

const liCount = (html: string): number => html.match(/<li /g)?.length ?? 0;

describe('一覧が出力する行の数', () => {
  it('全件描画版は 2,000 件なら 2,000 行を出力する', () => {
    expect(liCount(renderToString(<PlainProductList items={makeProducts(2000)} />))).toBe(2000);
  });

  it('仮想化版は 2,000 件でも 20,000 件でも最初は 15 行だけを出力する', () => {
    expect(liCount(renderToString(<VirtualProductList items={makeProducts(2000)} />))).toBe(15);
    expect(liCount(renderToString(<VirtualProductList items={makeProducts(20_000)} />))).toBe(15);
  });

  it('仮想化版の行は、全体の件数と自分の位置を aria-setsize / aria-posinset で持つ', () => {
    const html = renderToString(<VirtualProductList items={makeProducts(20_000)} />);
    expect(html).toContain('aria-setsize="20000"');
    expect(html).toContain('aria-posinset="15"');
    expect(html).not.toContain('aria-posinset="16"');
  });
});
