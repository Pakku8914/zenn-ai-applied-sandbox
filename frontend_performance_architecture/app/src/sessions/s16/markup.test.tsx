import { renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { products } from '../../data/products';
import { AccessibleList } from './AccessibleList';
import { BadCatalog } from './BadCatalog';
import { CategoryRadios } from './CategoryRadios';
import { GoodCatalog } from './GoodCatalog';
import { createCatalogApi, parseOptions } from './catalogApi';

const count = (html: string, pattern: RegExp): number => html.match(pattern)?.length ?? 0;
const api = () => createCatalogApi(parseOptions(''));

describe('マークアップ（renderToString で決定的に検査する）', () => {
  it('一覧は Tab で止まる行を 1 つだけ持ち、全件数と位置を属性で伝える', () => {
    const html = renderToString(<AccessibleList items={products} onOpen={() => undefined} />);
    expect(count(html, /<li /g)).toBe(15);
    expect(count(html, /tabindex="0"/g)).toBe(1);
    expect(count(html, /tabindex="-1"/g)).toBe(14);
    expect(html).toContain('aria-setsize="2000"');
    expect(html).toContain('aria-posinset="15"');
  });

  it('カテゴリは radiogroup で、選択中の 1 つだけが aria-checked="true"・tabindex="0"', () => {
    const html = renderToString(<CategoryRadios value="文具" onChange={() => undefined} />);
    expect(html).toContain('role="radiogroup"');
    expect(count(html, /role="radio"/g)).toBe(5);
    expect(count(html, /aria-checked="true"/g)).toBe(1);
    expect(count(html, /tabindex="0"/g)).toBe(1);
  });

  it('Good 版は最初から label・status・aria-busy を持ち、スケルトンは読み上げから外す', () => {
    const html = renderToString(<GoodCatalog api={api()} failLoad={false} liveDelayMs={300} />);
    expect(html).toContain('<label for="keyword"');
    expect(html).toContain('role="status"');
    expect(html).toContain('商品を読み込んでいます');
    expect(html).toContain('aria-busy="true"');
    expect(html).toMatch(/data-skeleton="true" aria-hidden="true"/);
  });

  it('Bad 版には label も status も無い', () => {
    const html = renderToString(<BadCatalog api={api()} failLoad={false} />);
    expect(html).not.toContain('<label');
    expect(html).not.toContain('role=');
    expect(html).toContain('data-spinner="true"');
  });
});
