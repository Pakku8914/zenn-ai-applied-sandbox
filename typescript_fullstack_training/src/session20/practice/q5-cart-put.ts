// 問題5: PUT（冪等）と POST（冪等でない）の違いを、動くサーバーで確かめる。
//
//   PUT  /api/cart/:productId  数量を「その値にする」   → 2回送っても結果は同じ
//   POST /api/cart/:productId  数量を「その分だけ足す」 → 2回送ると倍になる
//   GET  /api/cart             いまのカートの中身

import { createServer } from 'node:http';
import type { IncomingMessage, Server, ServerResponse } from 'node:http';
import type { CatalogItem } from '../../session17/catalog';
import { tryCatchAsync } from '../../session18/result';
import {
  MAX_CART_QUANTITY,
  findCatalogItem,
  loadCatalogSafely,
  parseQuantity,
  reserveStock,
} from '../../session18/shop';
import type { ShopError } from '../../session18/shop';
import { toErrorPayload, toHttpStatus } from '../error-status';
import { parseJson, readRequestBody, sendJson, withErrorHandling } from '../http-tools';
import { toRequestUrl } from '../url-parts';

const CART_ITEM_PATTERN = /^\/api\/cart\/(\d+)$/;

export type QuantityBody = { quantityInput: string };

export function isQuantityBody(value: unknown): value is QuantityBody {
  return (
    typeof value === 'object' &&
    value !== null &&
    'quantityInput' in value &&
    typeof value.quantityInput === 'string'
  );
}

/** '/api/cart/3' から 3 を取り出す */
export function matchCartProductId(pathname: string): number | undefined {
  const matched = CART_ITEM_PATTERN.exec(pathname);

  if (matched === null) {
    return undefined;
  }
  const captured = matched[1];
  return captured === undefined ? undefined : Number(captured);
}

export type CartServerOptions = {
  onError?: (error: unknown) => void;
  loadCatalog?: () => Promise<CatalogItem[]>;
};

function sendShopError(res: ServerResponse, error: ShopError): void {
  sendJson(res, toHttpStatus(error), toErrorPayload(error));
}

export function createCartServer(options: CartServerOptions = {}): Server {
  const onError =
    options.onError ??
    ((caught: unknown) => {
      console.error('[cart-server] 想定外のエラー', caught);
    });

  // このサーバーが覚えているカートの中身（productId → 数量）。
  // データベースはまだ使わないので、プロセスが終われば消える。
  const quantities = new Map<number, number>();

  /** 数量を決める。replace なら置き換え、add なら足す */
  async function applyQuantity(
    req: IncomingMessage,
    res: ServerResponse,
    productId: number,
    mode: 'replace' | 'add'
  ): Promise<void> {
    const bodyText = await tryCatchAsync(() => readRequestBody(req));
    if (bodyText.kind === 'error') {
      sendJson(res, 413, { error: { kind: 'body_too_large', message: bodyText.error.message } });
      return;
    }

    const parsed = parseJson(bodyText.value);
    // 型ガードを通した結果は変数に受け取る（絞り込んだ型をそのまま持ち回れる）
    const body: unknown = parsed.kind === 'ok' ? parsed.value : undefined;

    if (!isQuantityBody(body)) {
      sendJson(res, 400, {
        error: { kind: 'invalid_body', message: 'quantityInput（文字列）が必要です' },
      });
      return;
    }

    const quantity = parseQuantity(body.quantityInput);
    if (quantity.kind === 'error') {
      sendShopError(res, quantity.error);
      return;
    }

    const catalog = await loadCatalogSafely(options.loadCatalog);
    if (catalog.kind === 'error') {
      sendShopError(res, catalog.error);
      return;
    }

    const item = findCatalogItem(catalog.value, productId);
    if (item.kind === 'error') {
      sendShopError(res, item.error);
      return;
    }

    const current = quantities.get(productId) ?? 0;
    const next = mode === 'replace' ? quantity.value : current + quantity.value;

    if (next > MAX_CART_QUANTITY) {
      sendShopError(res, { kind: 'quantity_out_of_range', value: next });
      return;
    }

    // 在庫が足りるかは「合計した数量」で確かめる
    const reserved = reserveStock(item.value, next);
    if (reserved.kind === 'error') {
      sendShopError(res, reserved.error);
      return;
    }

    quantities.set(productId, next);
    sendJson(res, 200, reserved.value);
  }

  /** GET /api/cart。いまの中身と小計を返す */
  async function showCart(res: ServerResponse): Promise<void> {
    const catalog = await loadCatalogSafely(options.loadCatalog);
    if (catalog.kind === 'error') {
      sendShopError(res, catalog.error);
      return;
    }

    const items = [...quantities.entries()]
      .toSorted((left, right) => left[0] - right[0])
      .flatMap(([productId, quantity]) => {
        const item = findCatalogItem(catalog.value, productId);
        if (item.kind === 'error') {
          return [];
        }
        const reserved = reserveStock(item.value, quantity);
        return reserved.kind === 'ok' ? [reserved.value] : [];
      });

    const subtotal = items.reduce((total, line) => total + line.lineTotal, 0);
    sendJson(res, 200, { count: items.length, subtotal, items });
  }

  return createServer(
    withErrorHandling(async (req, res) => {
      const url = toRequestUrl(req);
      const method = req.method ?? 'GET';
      const productId = matchCartProductId(url.pathname);

      if (url.pathname === '/api/cart') {
        if (method !== 'GET') {
          res.setHeader('Allow', 'GET');
          sendJson(res, 405, {
            error: { kind: 'method_not_allowed', message: 'このURLでは GET だけを使えます' },
          });
          return;
        }
        await showCart(res);
        return;
      }

      if (productId !== undefined) {
        if (method === 'PUT') {
          await applyQuantity(req, res, productId, 'replace');
          return;
        }
        if (method === 'POST') {
          await applyQuantity(req, res, productId, 'add');
          return;
        }
        res.setHeader('Allow', 'PUT, POST');
        sendJson(res, 405, {
          error: { kind: 'method_not_allowed', message: 'このURLでは PUT / POST だけを使えます' },
        });
        return;
      }

      sendJson(res, 404, {
        error: { kind: 'route_not_found', message: `そのURLはありません: ${method} ${url.pathname}` },
      });
    }, onError)
  );
}
