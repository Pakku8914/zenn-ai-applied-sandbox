// セッション20「WebとHTTPの基礎・Node.jsサーバー」の到達点。
//
// ミニ雑貨ショップの API を node:http だけで作る。
//   GET  /api/products          商品一覧（?q=キーワード で絞り込み）
//   GET  /api/products/:id      商品1件
//   POST /api/cart              カートに追加
//   GET  /products              /api/products へリダイレクト
//
// 失敗はすべてセッション18の ShopError として受け取り、error-status.ts の表で
// ステータスコードに翻訳する。ここに if の羅列で 404 や 409 を書かない。

import { createServer } from 'node:http';
import type { IncomingMessage, Server, ServerResponse } from 'node:http';
import type { CatalogItem } from '../session17/catalog';
import { toLogSafeError } from '../session18/errors';
import { tryCatchAsync } from '../session18/result';
import type { Result } from '../session18/result';
import { addToCart, findCatalogItem, loadCatalogSafely } from '../session18/shop';
import type { ShopError } from '../session18/shop';
import { toErrorPayload, toHttpStatus } from './error-status';
import {
  parseJson,
  readRequestBody,
  sendJson,
  sendRedirect,
  withErrorHandling,
} from './http-tools';
import { toRequestUrl } from './url-parts';

/** カタログの読み込み。テストで失敗を再現するために差し替えられる */
export type CatalogLoader = () => Promise<CatalogItem[]>;

export type ShopServerOptions = {
  /** 想定外の例外を記録する。既定は console.error */
  onError?: (error: unknown) => void;
  /** カタログの読み込み処理（省略するとセッション17の loadCatalog を使う） */
  loadCatalog?: CatalogLoader;
};

/** POST /api/cart のリクエストボディの形 */
export type AddToCartBody = { productId: number; quantityInput: string };

/**
 * ボディの形を確かめる型ガード（セッション12）。
 * HTTP の向こうから来る値は unknown なので、必ずここを通してから使う。
 * ちなみに数量が文字列なのは、HTTP のフォームが送ってくるのが常に文字列だから。
 */
export function isAddToCartBody(value: unknown): value is AddToCartBody {
  return (
    typeof value === 'object' &&
    value !== null &&
    'productId' in value &&
    typeof value.productId === 'number' &&
    'quantityInput' in value &&
    typeof value.quantityInput === 'string'
  );
}

const PRODUCT_DETAIL_PATTERN = /^\/api\/products\/(\d+)$/;

/** '/api/products/3' から 3 を取り出す。数字以外のパスには一致させない */
export function matchProductId(pathname: string): number | undefined {
  const matched = PRODUCT_DETAIL_PATTERN.exec(pathname);

  if (matched === null) {
    return undefined;
  }
  // noUncheckedIndexedAccess が有効なので、取り出した値は string | undefined
  const captured = matched[1];
  return captured === undefined ? undefined : Number(captured);
}

/** 許されないメソッドで来た。使えるメソッドを Allow ヘッダで教える */
function sendMethodNotAllowed(res: ServerResponse, allowed: readonly string[]): void {
  res.setHeader('Allow', allowed.join(', '));
  sendJson(res, 405, {
    error: {
      kind: 'method_not_allowed',
      message: `このURLでは ${allowed.join(' / ')} だけを使えます`,
    },
  });
}

/** 失敗（ShopError）をそのままレスポンスにする */
function sendShopError(res: ServerResponse, error: ShopError): void {
  sendJson(res, toHttpStatus(error), toErrorPayload(error));
}

/** カタログを読む。読めなければ失敗をレスポンスにして false を返す */
async function loadCatalogOr(
  res: ServerResponse,
  loader: CatalogLoader | undefined
): Promise<Result<CatalogItem[], ShopError>> {
  const result = await loadCatalogSafely(loader);

  if (result.kind === 'error') {
    sendShopError(res, result.error);
  }
  return result;
}

/** GET /api/products */
async function handleProductList(
  url: URL,
  res: ServerResponse,
  loader: CatalogLoader | undefined
): Promise<void> {
  const catalog = await loadCatalogOr(res, loader);
  if (catalog.kind === 'error') {
    return;
  }

  const keyword = url.searchParams.get('q') ?? '';
  const items =
    keyword === '' ? catalog.value : catalog.value.filter((item) => item.name.includes(keyword));

  sendJson(res, 200, { count: items.length, items });
}

/** GET /api/products/:id */
async function handleProductDetail(
  productId: number,
  res: ServerResponse,
  loader: CatalogLoader | undefined
): Promise<void> {
  const catalog = await loadCatalogOr(res, loader);
  if (catalog.kind === 'error') {
    return;
  }

  const found = findCatalogItem(catalog.value, productId);
  if (found.kind === 'error') {
    sendShopError(res, found.error);
    return;
  }
  sendJson(res, 200, found.value);
}

/** POST /api/cart */
async function handleAddToCart(
  req: IncomingMessage,
  res: ServerResponse,
  loader: CatalogLoader | undefined
): Promise<void> {
  // ボディの読み取りは例外を投げうるので、境界で Result に変える（セッション18）
  const bodyResult = await tryCatchAsync(() => readRequestBody(req));
  if (bodyResult.kind === 'error') {
    sendJson(res, 413, {
      error: { kind: 'body_too_large', message: bodyResult.error.message },
    });
    return;
  }

  const parsed = parseJson(bodyResult.value);
  if (parsed.kind === 'error') {
    sendJson(res, 400, {
      error: { kind: 'invalid_json', message: 'リクエストボディを JSON として読めませんでした' },
    });
    return;
  }

  // 型ガードを通した結果は変数に受け取る（絞り込んだ型をそのまま持ち回れる）
  const body: unknown = parsed.value;
  if (!isAddToCartBody(body)) {
    sendJson(res, 400, {
      error: {
        kind: 'invalid_body',
        message: 'productId（数値）と quantityInput（文字列）が必要です',
      },
    });
    return;
  }

  const catalog = await loadCatalogOr(res, loader);
  if (catalog.kind === 'error') {
    return;
  }

  const reserved = addToCart(catalog.value, body.productId, body.quantityInput);
  if (reserved.kind === 'error') {
    sendShopError(res, reserved.error);
    return;
  }
  // 200 ではなく 201（Created）。「新しく作られた」ことをステータスコードで伝える
  sendJson(res, 201, reserved.value);
}

/** ルーティング。「メソッド × パス」の組で行き先を決める */
async function route(
  req: IncomingMessage,
  res: ServerResponse,
  loader: CatalogLoader | undefined
): Promise<void> {
  const url = toRequestUrl(req);
  const method = req.method ?? 'GET';
  const path = url.pathname;

  if (path === '/products') {
    sendRedirect(res, 301, '/api/products'); // 昔の URL は案内だけする
    return;
  }

  if (path === '/api/products') {
    if (method !== 'GET') {
      sendMethodNotAllowed(res, ['GET']);
      return;
    }
    await handleProductList(url, res, loader);
    return;
  }

  const productId = matchProductId(path);
  if (productId !== undefined) {
    if (method !== 'GET') {
      sendMethodNotAllowed(res, ['GET']);
      return;
    }
    await handleProductDetail(productId, res, loader);
    return;
  }

  if (path === '/api/cart') {
    if (method !== 'POST') {
      sendMethodNotAllowed(res, ['POST']);
      return;
    }
    await handleAddToCart(req, res, loader);
    return;
  }

  sendJson(res, 404, {
    error: { kind: 'route_not_found', message: `そのURLはありません: ${method} ${path}` },
  });
}

/** ショップの API サーバーを作る（待ち受けの開始はまだしない） */
export function createShopServer(options: ShopServerOptions = {}): Server {
  const onError =
    options.onError ??
    ((caught: unknown) => {
      // ログに出すのは「出してよい部分」だけ（セッション18）
      console.error('[shop-server] 想定外のエラー', toLogSafeError(caught));
    });

  return createServer(
    withErrorHandling((req, res) => route(req, res, options.loadCatalog), onError)
  );
}
