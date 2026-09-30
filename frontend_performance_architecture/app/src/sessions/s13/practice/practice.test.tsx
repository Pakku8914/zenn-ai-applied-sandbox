import { renderToStaticMarkup, renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { products, type Product } from '../../../data/products';
import { parseCartItem, readCart } from './cartItem';
import { CheapProducts, selectCheap } from './CheapProducts';
import { CheapProductsBad } from './CheapProductsBad';
import { formatPoints, formatPrice, formatShippingFee } from './formatters';
import { isHighlighted, ProductRow, ProductRows } from './ProductRow';
import { ProductRowBad } from './ProductRowBad';
import { productColumns } from './productColumns';
import { CartBadge, CatalogShell, ShellHeader } from './Shell';
import { CatalogShellBad } from './ShellBad';
import { SimpleTable } from './SimpleTable';
import { StockBadge, toStockStatus } from './StockBadge';

const count = (html: string, pattern: RegExp) => (html.match(pattern) ?? []).length;
const noop = () => {};
const three = products.slice(0, 3);
const first = three[0]!;

describe('問題1：表示専用への切り出し', () => {
  it('150 円以下は 11 件で、安い順に並ぶ', () => {
    const cheap = selectCheap(products, 150);
    expect(cheap).toHaveLength(11);
    expect(cheap[0]).toMatchObject({ name: '商品1873', price: 101 });
    expect(cheap.at(-1)).toMatchObject({ name: '商品804', price: 148 });
    expect(products[0]?.name).toBe('商品1'); // 元の配列は並べ替えていない
  });

  it.each([150, 100])('%i 円以下で分割前と同じ HTML', (maxPrice) => {
    expect(renderToString(<CheapProducts items={products} maxPrice={maxPrice} />)).toBe(
      renderToString(<CheapProductsBad maxPrice={maxPrice} />),
    );
  });

  it('データの出どころを差し替えられる', () => {
    const html = renderToStaticMarkup(<CheapProducts items={three} maxPrice={200} />);
    expect(html).toContain('<li>商品1：137 円</li><li>商品2：174 円</li>');
  });
});

describe('問題2：在庫表示を判別可能ユニオンにする', () => {
  it.each<[number, ReturnType<typeof toStockStatus>]>([
    [0, { kind: 'soldOut' }],
    [-1, { kind: 'soldOut' }],
    [3, { kind: 'few', remaining: 3 }],
    [5, { kind: 'few', remaining: 5 }],
    [6, { kind: 'inStock' }],
  ])('残り %i 点', (remaining, expected) => {
    expect(toStockStatus(remaining)).toEqual(expected);
  });

  it('状態ごとの表示', () => {
    expect(renderToStaticMarkup(<StockBadge status={{ kind: 'inStock' }} />)).toBe('<span class="stock">在庫あり</span>');
    expect(renderToStaticMarkup(<StockBadge status={{ kind: 'few', remaining: 3 }} />)).toBe(
      '<span class="stock stock-few">残り3点</span>',
    );
    expect(renderToStaticMarkup(<StockBadge status={{ kind: 'soldOut' }} />)).toBe(
      '<span class="stock stock-out">売り切れ</span>',
    );
  });
});

describe('問題3：保存データを unknown で受けて検証する', () => {
  const productIdError = 'productId は 1 以上の整数にしてください';
  const quantityError = 'quantity は 1〜99 の整数にしてください';

  it('正しい形なら受け取る', () => {
    expect(parseCartItem({ productId: 1, quantity: 2 })).toEqual({ ok: true, value: { productId: 1, quantity: 2 } });
  });

  it.each<[string, unknown, string]>([
    ['null', null, 'オブジェクトではありません'],
    ['配列', [1, 2], 'オブジェクトではありません'],
    ['productId が文字列', { productId: '1', quantity: 2 }, productIdError],
    ['productId が 0', { productId: 0, quantity: 2 }, productIdError],
    ['productId が小数', { productId: 1.5, quantity: 2 }, productIdError],
    ['quantity が 0', { productId: 1, quantity: 0 }, quantityError],
    ['quantity が 100', { productId: 1, quantity: 100 }, quantityError],
    ['quantity が無い', { productId: 1 }, quantityError],
  ])('%s', (_label, input, reason) => {
    expect(parseCartItem(input)).toEqual({ ok: false, reason });
  });

  it('壊れた保存データからは空のカートを復元する', () => {
    expect(readCart(null)).toEqual([]);
    expect(readCart('{壊れた')).toEqual([]);
    expect(readCart('{"productId":1,"quantity":2}')).toEqual([]);
  });

  it('形の違う要素は読み飛ばし、余分な項目は落とす', () => {
    const raw = '[{"productId":1,"quantity":2,"price":0},{"productId":"x","quantity":1},{"productId":5,"quantity":3}]';
    expect(readCart(raw)).toStrictEqual([
      { productId: 1, quantity: 2 },
      { productId: 5, quantity: 3 },
    ]);
  });
});

describe('問題4：バケツリレーを合成で解く', () => {
  it('中継をやめても同じ HTML', () => {
    expect(renderToString(<CatalogShell cartCount={3} items={three} />)).toBe(
      renderToString(<CatalogShellBad cartCount={3} items={three} />),
    );
  });

  it('カートの数は CartBadge だけが知っている', () => {
    expect(renderToStaticMarkup(<CartBadge count={3} />)).toBe('<span aria-label="カートの商品数">カート（3）</span>');
  });

  it('見出しはカート以外の操作とも組み合わせられる', () => {
    expect(renderToStaticMarkup(<ShellHeader title="ヘルプ" actions={<a href="/">戻る</a>} />)).toBe(
      '<header><h1>ヘルプ</h1><a href="/">戻る</a></header>',
    );
    expect(renderToStaticMarkup(<ShellHeader title="ヘルプ" />)).toBe('<header><h1>ヘルプ</h1></header>');
  });
});

describe('問題5：依存の向きを直す', () => {
  it('Bad は window の無い環境では描画できない', () => {
    expect(() => renderToString(<ProductRowBad product={first} />)).toThrow('window is not defined');
  });

  it('Good は props だけで描画できる', () => {
    expect(renderToStaticMarkup(<ProductRow product={first} highlighted onAdd={noop} />)).toBe(
      '<li><span><mark>商品1</mark></span><button type="button">カートに入れる</button></li>',
    );
  });

  it('強調の判定は純粋関数', () => {
    expect(isHighlighted('商品10', '商品1')).toBe(true);
    expect(isHighlighted('商品2', '商品1')).toBe(false);
    expect(isHighlighted('商品1', '')).toBe(false);
  });

  it('組み立て役がキーワードを渡す', () => {
    const html = renderToStaticMarkup(<ProductRows items={three} keyword="商品1" addToCart={noop} />);
    expect(count(html, /<mark>/g)).toBe(1);
  });
});

describe('問題6：似ているだけの関数を分けたままにする', () => {
  it('価格だけが税込表示に変わり、送料とポイントは変わらない', () => {
    expect(formatPrice(1200)).toBe('1,200 円（税込）');
    expect(formatShippingFee(0)).toBe('送料無料');
    expect(formatShippingFee(1500)).toBe('送料 1,500 円');
    expect(formatPoints(1234)).toBe('1,234 pt');
  });
});

describe('問題7：3回目で切り出す再利用部品', () => {
  it('商品の列を選んで表にする', () => {
    const html = renderToStaticMarkup(
      <SimpleTable rows={products.slice(0, 2)} columns={[productColumns.name, productColumns.price]} rowKey={(p) => p.id} />,
    );
    expect(html).toContain('<th style="text-align:left">商品名</th><th style="text-align:right">価格</th>');
    expect(html).toContain('<td style="text-align:left">商品2</td><td style="text-align:right">174 円（税込）</td>');
    expect(count(html, /<tr>/g)).toBe(3);
  });

  it('行が無ければ空の表示', () => {
    const rows: Product[] = [];
    expect(renderToStaticMarkup(<SimpleTable rows={rows} columns={[productColumns.name]} rowKey={(p) => p.id} />)).toBe(
      '<p>該当するデータはありません</p>',
    );
  });

  it('商品以外の行にも使える（部品は商品を知らない）', () => {
    const rows = [{ label: '送料', value: formatShippingFee(0) }];
    const html = renderToStaticMarkup(
      <SimpleTable
        rows={rows}
        columns={[
          { header: '項目', render: (r) => r.label },
          { header: '金額', render: (r) => r.value, align: 'right' },
        ]}
        rowKey={(r) => r.label}
      />,
    );
    expect(html).toContain('<td style="text-align:left">送料</td><td style="text-align:right">送料無料</td>');
  });
});
