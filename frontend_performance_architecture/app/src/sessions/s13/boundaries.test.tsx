import { renderToStaticMarkup, renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { ProductList } from '../../components/ProductList';
import { products } from '../../data/products';
import type { RequestState } from '../s10/requestState';
import { CATEGORY_ALL, filterProducts } from '../s09/catalogQuery';
import { ProductListBad } from './bad/ProductListBad';
import { CatalogContent, CatalogPage } from './catalog/CatalogPage';
import { loadProducts } from './catalog/loadProducts';
import { ProductCatalog } from './catalog/ProductCatalog';
import { ProductListView } from './catalog/ProductListView';
import { isProduct, MAX_PRODUCTS, parseProducts } from './catalog/productGuard';
import { PageLayout } from './ui/PageLayout';

const visible = (keyword: string) => filterProducts(products, { keyword, category: CATEGORY_ALL });
const count = (html: string, pattern: RegExp) => (html.match(pattern) ?? []).length;
const noop = () => {};
// 通信を経由した値を模す（型の情報が消えて unknown になる）
const overTheWire = (value: unknown): unknown => JSON.parse(JSON.stringify(value));
const valid = { id: 1, name: '商品1', price: 137, category: '書籍' };

describe('分割前後で画面の出力が変わらない', () => {
  it.each(['', '商品10', '該当なし'])('キーワード「%s」で出発点の ProductList と同じ HTML', (keyword) => {
    expect(renderToString(<ProductListView items={visible(keyword)} />)).toBe(
      renderToString(<ProductList keyword={keyword} />),
    );
  });

  it('全件で 2000 行、「商品10」で 111 行', () => {
    expect(count(renderToString(<ProductListView items={visible('')} />), /<li /g)).toBe(2000);
    expect(count(renderToString(<ProductListView items={visible('商品10')} />), /<li /g)).toBe(111);
  });

  it('状態を持つ部品は、入力欄と表示部品の出力を並べるだけ', () => {
    const html = renderToString(<ProductCatalog items={products} initialKeyword="商品10" />);
    expect(html).toContain('value="商品10"');
    expect(html).toContain(renderToString(<ProductListView items={visible('商品10')} />));
  });
});

describe('判別可能ユニオンの props（ListMode）', () => {
  const three = products.slice(0, 3);

  it('browse は操作を出さない', () => {
    const html = renderToStaticMarkup(<ProductListView items={three} />);
    expect(count(html, /<button/g)).toBe(0);
    expect(count(html, /type="checkbox"/g)).toBe(0);
  });

  it('cart は行ごとに「カートに入れる」を出す', () => {
    const html = renderToStaticMarkup(<ProductListView items={three} mode={{ kind: 'cart', onAdd: noop }} />);
    expect(count(html, /カートに入れる/g)).toBe(3);
  });

  it('compare は選ばれた行だけチェックを付ける', () => {
    const mode = { kind: 'compare', selectedIds: new Set([1, 3]), onToggle: noop } as const;
    const html = renderToStaticMarkup(<ProductListView items={three} mode={mode} />);
    expect(count(html, /type="checkbox"/g)).toBe(3);
    expect(count(html, /checked=""/g)).toBe(2);
  });

  it('Bad：onAdd を渡し忘れても型は通り、押しても何も起きないボタンが出る', () => {
    const html = renderToStaticMarkup(<ProductListBad items={three} showAddButton />);
    expect(count(html, /カートに入れる/g)).toBe(3);
  });

  it('Bad：フラグを両方立てると、ボタンとチェックボックスが同時に出る', () => {
    const html = renderToStaticMarkup(<ProductListBad items={three} showAddButton showCompare />);
    expect(count(html, /<button/g)).toBe(3);
    expect(count(html, /type="checkbox"/g)).toBe(3);
  });
});

describe('外から来る値を unknown で受けて型ガードで絞り込む', () => {
  it('通信を経由した 2,000 件はすべて商品として受け取れる', () => {
    const result = parseProducts(overTheWire(products));
    expect(result.ok && result.value.length).toBe(2000);
  });

  it('余分な項目は写さずに落とす', () => {
    expect(isProduct({ ...valid, secret: 'x' })).toBe(true);
    expect(parseProducts([{ ...valid, secret: 'x' }])).toStrictEqual({ ok: true, value: [valid] });
  });

  it.each<[string, unknown, string]>([
    ['null', null, '商品の一覧が配列ではありません'],
    ['オブジェクトで包まれている', { items: [valid] }, '商品の一覧が配列ではありません'],
    ['価格が文字列', [{ ...valid, price: '137' }], '0 番目の要素が商品の形をしていません'],
    ['項目が足りない', [valid, { id: 2, name: '商品2' }], '1 番目の要素が商品の形をしていません'],
    ['要素が null', [valid, null], '1 番目の要素が商品の形をしていません'],
    ['要素が配列', [[1, '商品1', 137, '書籍']], '0 番目の要素が商品の形をしていません'],
    ['価格が NaN', [{ ...valid, price: Number.NaN }], '0 番目の要素が商品の形をしていません'],
  ])('%s は失敗として理由を返す', (_label, input, reason) => {
    expect(parseProducts(input)).toEqual({ ok: false, reason });
  });

  it('上限を超える件数は受け取らない', () => {
    const tooMany = Array.from({ length: MAX_PRODUCTS + 1 }, () => valid);
    expect(parseProducts(tooMany)).toEqual({ ok: false, reason: '商品が多すぎます（上限 10000 件）' });
  });
});

describe('データを取る部品', () => {
  const messageOf = (state: RequestState<unknown>) => (state.status === 'error' ? state.error.message : state.status);

  it('正しい形なら success', async () => {
    const state = await loadProducts(async () => overTheWire(products.slice(0, 3)));
    expect(state).toEqual({ status: 'success', data: products.slice(0, 3) });
  });

  it('形が違えば error（例外にしない）', async () => {
    expect(messageOf(await loadProducts(async () => ({ items: [] })))).toBe('商品の一覧が配列ではありません');
  });

  it('通信の失敗も error', async () => {
    const failing = async () => {
      throw new Error('通信に失敗しました');
    };
    expect(messageOf(await loadProducts(failing))).toBe('通信に失敗しました');
    expect(messageOf(await loadProducts(() => Promise.reject('時間切れ')))).toBe('時間切れ');
  });

  it('状態ごとに出すものが決まっている', () => {
    expect(renderToStaticMarkup(<CatalogContent state={{ status: 'loading' }} />)).toBe('<p>読み込み中…</p>');
    expect(renderToStaticMarkup(<CatalogContent state={{ status: 'error', error: new Error('通信に失敗しました') }} />)).toBe(
      '<p role="alert">商品を読み込めませんでした（通信に失敗しました）</p>',
    );
    const success = renderToStaticMarkup(<CatalogContent state={{ status: 'success', data: products }} />);
    expect(success).toContain('id="keyword"');
    expect(success).toContain('商品一覧（2000 件）');
  });

  it('描画しただけでは取得しない（取得は effect の中）', () => {
    const load = vi.fn(async () => products);
    expect(renderToStaticMarkup(<CatalogPage load={load} />)).toBe('<p>読み込み中…</p>');
    expect(load).not.toHaveBeenCalled();
  });
});

describe('再利用できる部品（PageLayout）', () => {
  it('中身を知らずに、置き場所へ並べるだけ', () => {
    const html = renderToStaticMarkup(
      <PageLayout title="商品カタログ" toolbar={<button type="button">並び替え</button>}>
        <p>本文</p>
      </PageLayout>,
    );
    expect(html).toContain('<h1>商品カタログ</h1>');
    expect(html).toContain('<div style="margin-bottom:16px"><button type="button">並び替え</button></div>');
    expect(html).toContain('<p>本文</p>');
  });

  it('toolbar を渡さなければ枠を出さない', () => {
    expect(renderToStaticMarkup(<PageLayout title="t">x</PageLayout>)).not.toContain('<div');
  });
});
