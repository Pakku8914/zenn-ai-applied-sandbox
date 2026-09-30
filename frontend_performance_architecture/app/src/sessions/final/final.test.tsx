import { renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { PRODUCTS_20K } from '../s08/products20k';
import { NO_MATCH_MESSAGE } from '../s16/a11yModel';
import { Catalog } from './done/features/catalog';
import { countHeading, filterByKeyword, statusMessage } from './done/features/catalog/catalogView';
import { loadPrintRenderer } from './done/features/print/loadPrintRenderer';
import { StartCatalog } from './start/StartCatalog';

const count = (html: string, pattern: RegExp): number => html.match(pattern)?.length ?? 0;

describe('絞り込みと件数の文言（純粋関数）', () => {
  it('20,000 件をキーワードで絞り込んだ件数', () => {
    expect(filterByKeyword(PRODUCTS_20K, '')).toHaveLength(20_000);
    expect(filterByKeyword(PRODUCTS_20K, '商品1')).toHaveLength(11_111);
    expect(filterByKeyword(PRODUCTS_20K, '商品10')).toHaveLength(1_111);
    expect(filterByKeyword(PRODUCTS_20K, '商品20001')).toHaveLength(0);
  });

  it('見出しは計測スクリプトが読む書式（3 桁区切りなし）、読み上げは 3 桁区切り', () => {
    expect(countHeading(11_111)).toBe('商品一覧（11111 件）');
    expect(statusMessage(20_000, 20_000, '')).toBe('全 20,000 件を表示しています');
    expect(statusMessage(11_111, 20_000, '商品1')).toBe('11,111 件見つかりました');
    expect(statusMessage(0, 20_000, '商品20001')).toBe(NO_MATCH_MESSAGE);
  });
});

describe('マークアップ（renderToString で決定的に検査する）', () => {
  it('模範解答版の一覧は 20,000 件でも 15 行だけを描き、Tab で止まる行は 1 つ', () => {
    const html = renderToString(<Catalog items={PRODUCTS_20K} onSelect={() => undefined} />);
    expect(count(html, /<li /g)).toBe(15);
    expect(count(html, /tabindex="0"/g)).toBe(1);
    expect(count(html, /tabindex="-1"/g)).toBe(14);
    expect(html).toContain('aria-setsize="20000"');
    expect(html).toContain('role="status"');
    expect(html).toContain('全 20,000 件を表示しています');
    expect(html).toContain('商品一覧（20000 件）');
  });

  it('出題版は 20,000 行をすべて描き、行のボタンがすべて Tab に並び、件数の読み上げが無い', () => {
    const html = renderToString(<StartCatalog />);
    expect(count(html, /<li /g)).toBe(20_000);
    expect(count(html, /<button /g)).toBe(20_001); // 「グラフを表示」＋ 20,000 行
    expect(html).not.toContain('tabindex');
    expect(html).not.toContain('role="status"');
  });
});

describe('印刷の部品の遅延読み込み', () => {
  it('初回だけ読み込み、2 回目以降は同じ Promise を返す', async () => {
    const first = loadPrintRenderer();
    expect(loadPrintRenderer()).toBe(first);
    const render = await first;
    const product = PRODUCTS_20K[0];
    expect(product).toBeDefined();
    if (product === undefined) return;
    expect(render(product)).toBe('<article class="print-card"><h2>商品1</h2><p>137 円</p><p>書籍</p></article>');
  });
});
