// セッション20のユニットテスト。
// 実行: docker compose exec ts npx vitest run src/session20

import { describe, expect, it } from 'vitest';
import type { ShopError } from '../session18/shop';
import { toErrorPayload, toHttpStatus } from './error-status';
import { buildSetCookieHeader, parseCookieHeader } from './http-tools';
import { closeServer, listenOnRandomPort } from './server-utils';
import { createShopServer, isAddToCartBody, matchProductId } from './shop-server';

describe('matchProductId', () => {
  it.each([
    ['/api/products/3', 3],
    ['/api/products/999', 999],
  ])('%s から数字を取り出す', (path, expected) => {
    expect(matchProductId(path)).toBe(expected);
  });

  it.each(['/api/products', '/api/products/', '/api/products/abc', '/api/products/3/reviews'])(
    '%s には一致しない',
    (path) => {
      expect(matchProductId(path)).toBeUndefined();
    }
  );
});

describe('toHttpStatus', () => {
  it('入力の不正は400、商品が無ければ404、在庫不足は409になる', () => {
    const invalid: ShopError = { kind: 'invalid_quantity', input: 'abc' };
    const notFound: ShopError = { kind: 'product_not_found', productId: 99 };
    const soldOut: ShopError = {
      kind: 'out_of_stock',
      productName: 'リネンのふきん',
      requested: 1,
      available: 0,
    };

    expect(toHttpStatus(invalid)).toBe(400);
    expect(toHttpStatus(notFound)).toBe(404);
    expect(toHttpStatus(soldOut)).toBe(409);
  });

  it('5xx では内部のメッセージを外に出さない', () => {
    const down: ShopError = { kind: 'catalog_unavailable', reason: '/work/fixtures が読めません' };

    expect(toHttpStatus(down)).toBe(503);
    expect(toErrorPayload(down)).toEqual({
      error: {
        kind: 'catalog_unavailable',
        message: 'サーバー側の問題でリクエストを処理できませんでした',
      },
    });
  });
});

describe('Cookie の組み立てと解析', () => {
  it('Set-Cookie には必ず HttpOnly / Secure / SameSite が付く', () => {
    const header = buildSetCookieHeader('shop_session', 'abc123');

    expect(header).toContain('HttpOnly');
    expect(header).toContain('Secure');
    expect(header).toContain('SameSite=Lax');
  });

  it('ブラウザが送り返した Cookie ヘッダを解析できる', () => {
    const cookies = parseCookieHeader('shop_session=abc123; theme=dark');

    expect(cookies.get('shop_session')).toBe('abc123');
    expect(cookies.get('theme')).toBe('dark');
  });
});

describe('isAddToCartBody', () => {
  it('productId が数値・quantityInput が文字列のときだけ true になる', () => {
    expect(isAddToCartBody({ productId: 1, quantityInput: '2' })).toBe(true);
    expect(isAddToCartBody({ productId: '1', quantityInput: '2' })).toBe(false);
    expect(isAddToCartBody({ productId: 1, quantityInput: 2 })).toBe(false);
    expect(isAddToCartBody(undefined)).toBe(false);
  });
});

describe('createShopServer', () => {
  /** サーバーを立ててリクエストを送り、必ず後片付けする */
  async function withServer<T>(run: (baseUrl: string) => Promise<T>): Promise<T> {
    const server = createShopServer({ onError: () => {} });

    try {
      const port = await listenOnRandomPort(server);
      return await run(`http://127.0.0.1:${port}`);
    } finally {
      await closeServer(server);
    }
  }

  it('GET /api/products/3 はマグカップを返す', async () => {
    const body = await withServer(async (baseUrl) => {
      const res = await fetch(`${baseUrl}/api/products/3`);
      expect(res.status).toBe(200);

      const value: unknown = await res.json();
      return value;
    });

    expect(body).toEqual({
      id: 3,
      name: 'マグカップ',
      price: 2350,
      stock: 3,
      categoryName: 'キッチン雑貨',
    });
  });

  it('在庫切れの商品をカートに入れようとすると409になる', async () => {
    const result = await withServer(async (baseUrl) => {
      const res = await fetch(`${baseUrl}/api/cart`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ productId: 4, quantityInput: '1' }),
      });
      return { status: res.status, text: await res.text() };
    });

    expect(result.status).toBe(409);
    expect(result.text).toContain('out_of_stock');
  });

  it('知らないパスは404になる', async () => {
    const result = await withServer(async (baseUrl) => {
      const res = await fetch(`${baseUrl}/api/unknown`);
      return { status: res.status, text: await res.text() };
    });

    expect(result.status).toBe(404);
    expect(result.text).toContain('route_not_found');
  });
});
