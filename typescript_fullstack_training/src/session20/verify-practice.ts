// セッション20 練習問題の解答（076）の検証スクリプト。
//
// サーバーは空きポートで起動し、検証が終わったら必ず停止する。
// 実行: docker compose exec ts npx tsx src/session20/verify-practice.ts

import type { Category } from '../session17/catalog';
import { closeServer, listenOnRandomPort } from './server-utils';
import { formatUrlSummary, readPageNumber, toRequestTarget } from './practice/q1-url';
import { formatMethodTable, isRetrySafe, listUnsafeToRetry } from './practice/q2-methods';
import {
  buildAllowHeader,
  buildSessionCookie,
  describeShopErrorV2,
  toErrorPayloadV2,
  toHttpStatusV2,
} from './practice/q3-status';
import type { ShopErrorV2 } from './practice/q3-status';
import { createCategoryServer } from './practice/q4-categories-server';
import { createCartServer } from './practice/q5-cart-put';
import { createRoutedServer, matchPath, matchRoute } from './practice/q6-router';
import type { Route } from './practice/q6-router';
import { shopRoutes } from './practice/q6-routes';

let failedCount = 0;

function checkString(label: string, actual: string, expected: string): void {
  if (actual !== expected) {
    console.error(`NG: ${label}\n--- 期待値 ---\n${expected}\n--- 実際 ---\n${actual}`);
    failedCount += 1;
  }
}

function checkNumber(label: string, actual: number, expected: number): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 ${expected} / 実際 ${actual}`);
    failedCount += 1;
  }
}

type RequestOptions = { method?: string; headers?: Record<string, string>; body?: string };
type Fetched = { status: number; allow: string; body: string };

async function request(
  baseUrl: string,
  path: string,
  options: RequestOptions = {}
): Promise<Fetched> {
  const res = await fetch(`${baseUrl}${path}`, options);

  return {
    status: res.status,
    allow: res.headers.get('allow') ?? '(なし)',
    body: await res.text(),
  };
}

function jsonBody(method: string, payload: unknown): RequestOptions {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  };
}

// ---------------------------------------------------------------------------
// 問題1: URL の分解
// ---------------------------------------------------------------------------
const sampleUrl = 'https://shop.example.com:8443/api/products?q=soap&page=2#reviews';

checkString(
  '問題1: URL の要約',
  formatUrlSummary(sampleUrl),
  'origin: https://shop.example.com:8443\n' +
    'サーバーに届く部分: /api/products?q=soap&page=2\n' +
    'ブラウザだけが使う部分: #reviews'
);

checkString(
  '問題1: サーバーに届く部分',
  toRequestTarget('https://shop.example.com/products/3#reviews'),
  '/products/3'
);

checkString(
  '問題1: page の読み取り',
  [
    readPageNumber(sampleUrl),
    readPageNumber('https://shop.example.com/api/products'),
    readPageNumber('https://shop.example.com/api/products?page=abc'),
    readPageNumber('https://shop.example.com/api/products?page=0'),
  ].join(' / '),
  '2 / 1 / 1 / 1'
);

// ---------------------------------------------------------------------------
// 問題2: メソッドの安全性と冪等性
// ---------------------------------------------------------------------------
checkString(
  '問題2: メソッドの表',
  formatMethodTable(),
  'GET: 安全=はい / 冪等=はい / 取得する\n' +
    'POST: 安全=いいえ / 冪等=いいえ / 新しく作る・処理を起こす\n' +
    'PUT: 安全=いいえ / 冪等=はい / 内容をまるごと置き換える\n' +
    'PATCH: 安全=いいえ / 冪等=いいえ / 一部だけ書き換える\n' +
    'DELETE: 安全=いいえ / 冪等=はい / 削除する'
);

checkString('問題2: 送り直しが危ないメソッド', listUnsafeToRetry(), 'POST / PATCH');
checkString(
  '問題2: DELETE は送り直してよい',
  `${String(isRetrySafe('DELETE'))} / ${String(isRetrySafe('POST'))}`,
  'true / false'
);

// ---------------------------------------------------------------------------
// 問題3: ステータスコードとヘッダ
// ---------------------------------------------------------------------------
const cartFull: ShopErrorV2 = { kind: 'cart_full', currentLines: 3 };
const notFoundV2: ShopErrorV2 = { kind: 'product_not_found', productId: 99 };
const downV2: ShopErrorV2 = { kind: 'catalog_unavailable', reason: 'fixtures が読めません' };

checkString(
  '問題3: 拡張した対応表',
  [cartFull, notFoundV2, downV2].map((error) => `${error.kind} → ${toHttpStatusV2(error)}`).join('\n'),
  'cart_full → 409\nproduct_not_found → 404\ncatalog_unavailable → 503'
);

checkString(
  '問題3: 追加した失敗の説明',
  describeShopErrorV2(cartFull),
  'カートの明細が上限3件に達しています（現在 3件）'
);

checkString(
  '問題3: 409 の本文',
  JSON.stringify(toErrorPayloadV2(cartFull)),
  '{"error":{"kind":"cart_full","message":"カートの明細が上限3件に達しています（現在 3件）"}}'
);

checkString(
  '問題3: 503 の本文は中身を伏せる',
  JSON.stringify(toErrorPayloadV2(downV2)),
  '{"error":{"kind":"catalog_unavailable",' +
    '"message":"サーバー側の問題でリクエストを処理できませんでした"}}'
);

checkString('問題3: Allow ヘッダ', buildAllowHeader(['GET', 'POST']), 'GET, POST');
checkString(
  '問題3: セッション Cookie',
  buildSessionCookie('sess_abc'),
  'shop_session=sess_abc; Path=/; Max-Age=1800; HttpOnly; Secure; SameSite=Lax'
);

// ---------------------------------------------------------------------------
// 問題4: GET /api/categories
// ---------------------------------------------------------------------------
const categoryServer = createCategoryServer({ onError: () => {} });

try {
  const port = await listenOnRandomPort(categoryServer);
  const baseUrl = `http://127.0.0.1:${port}`;

  const list = await request(baseUrl, '/api/categories');
  checkNumber('問題4: 一覧は200', list.status, 200);
  checkString(
    '問題4: 一覧の本文',
    list.body,
    '{"count":3,"items":[' +
      '{"id":1,"name":"バス・ボディケア","slug":"bath-body"},' +
      '{"id":2,"name":"キッチン雑貨","slug":"kitchen"},' +
      '{"id":3,"name":"ファブリック","slug":"fabric"}]}'
  );

  const posted = await request(baseUrl, '/api/categories', { method: 'POST' });
  checkNumber('問題4: POST は405', posted.status, 405);
  checkString('問題4: Allow ヘッダ', posted.allow, 'GET');

  const unknown = await request(baseUrl, '/api/tags');
  checkNumber('問題4: 知らないパスは404', unknown.status, 404);
} finally {
  await closeServer(categoryServer);
}

const brokenCategoryServer = createCategoryServer({
  onError: () => {},
  loadCategories: (): Promise<Category[]> => {
    throw new Error('categories.json を読めません');
  },
});

try {
  const port = await listenOnRandomPort(brokenCategoryServer);
  const response = await request(`http://127.0.0.1:${port}`, '/api/categories');

  checkNumber('問題4: 読み込み失敗は503', response.status, 503);
} finally {
  await closeServer(brokenCategoryServer);
}

// ---------------------------------------------------------------------------
// 問題5: PUT は冪等・POST は冪等でない
// ---------------------------------------------------------------------------
const cartServer = createCartServer({ onError: () => {} });

try {
  const port = await listenOnRandomPort(cartServer);
  const baseUrl = `http://127.0.0.1:${port}`;
  const twoSoaps = jsonBody('PUT', { quantityInput: '2' });

  const first = await request(baseUrl, '/api/cart/1', twoSoaps);
  const second = await request(baseUrl, '/api/cart/1', twoSoaps);

  checkNumber('問題5: PUT は200', first.status, 200);
  checkString(
    '問題5: PUT の本文',
    first.body,
    '{"productId":1,"productName":"ラベンダーの石けん","quantity":2,"lineTotal":960}'
  );
  checkString('問題5: PUT を2回送っても結果が変わらない', second.body, first.body);

  const added = await request(baseUrl, '/api/cart/1', jsonBody('POST', { quantityInput: '2' }));
  checkString(
    '問題5: POST は数量が増える',
    added.body,
    '{"productId":1,"productName":"ラベンダーの石けん","quantity":4,"lineTotal":1920}'
  );

  const addedAgain = await request(baseUrl, '/api/cart/1', jsonBody('POST', { quantityInput: '2' }));
  checkString(
    '問題5: POST を2回送るとさらに増える',
    addedAgain.body,
    '{"productId":1,"productName":"ラベンダーの石けん","quantity":6,"lineTotal":2880}'
  );

  const soldOut = await request(baseUrl, '/api/cart/4', jsonBody('PUT', { quantityInput: '1' }));
  checkNumber('問題5: 在庫切れは409', soldOut.status, 409);

  const missing = await request(baseUrl, '/api/cart/99', jsonBody('PUT', { quantityInput: '1' }));
  checkNumber('問題5: 無い商品は404', missing.status, 404);

  const zero = await request(baseUrl, '/api/cart/1', jsonBody('PUT', { quantityInput: '0' }));
  checkNumber('問題5: 範囲外の数量は400', zero.status, 400);

  const overLimit = await request(baseUrl, '/api/cart/1', jsonBody('POST', { quantityInput: '9' }));
  checkNumber('問題5: 上限を超える追加は400', overLimit.status, 400);

  const deleted = await request(baseUrl, '/api/cart/1', { method: 'DELETE' });
  checkNumber('問題5: 未対応のメソッドは405', deleted.status, 405);
  checkString('問題5: Allow ヘッダ', deleted.allow, 'PUT, POST');

  const cart = await request(baseUrl, '/api/cart');
  checkString(
    '問題5: カートの中身',
    cart.body,
    '{"count":1,"subtotal":2880,"items":[' +
      '{"productId":1,"productName":"ラベンダーの石けん","quantity":6,"lineTotal":2880}]}'
  );
} finally {
  await closeServer(cartServer);
}

// ---------------------------------------------------------------------------
// 問題6: ルート表によるルーティング
// ---------------------------------------------------------------------------
checkString(
  '問題6: パスの照合',
  [
    // JSON.stringify(undefined) は文字列ではなく値 undefined を返す。
    // join はそれを空文字にしてしまうので、String() で明示的に文字にする
    // （章の出力例と同じ「undefined」という表示にそろえるため）。
    String(JSON.stringify(matchPath('/api/products/:id', '/api/products/3'))),
    String(JSON.stringify(matchPath('/api/products/:id', '/api/products/'))),
    String(JSON.stringify(matchPath('/api/products/:id', '/api/products/3/reviews'))),
    String(JSON.stringify(matchPath('/api/health', '/api/health'))),
  ].join('\n'),
  '{"id":"3"}\nundefined\nundefined\n{}'
);

const sampleRoutes: readonly Route[] = shopRoutes;

checkString(
  '問題6: 照合の結果',
  [
    matchRoute(sampleRoutes, 'GET', '/api/products/3').kind,
    matchRoute(sampleRoutes, 'DELETE', '/api/products/3').kind,
    matchRoute(sampleRoutes, 'GET', '/api/orders').kind,
  ].join(' / '),
  'matched / method_not_allowed / not_found'
);

const routedServer = createRoutedServer(shopRoutes, () => {});

try {
  const port = await listenOnRandomPort(routedServer);
  const baseUrl = `http://127.0.0.1:${port}`;

  const health = await request(baseUrl, '/api/health');
  checkNumber('問題6: ヘルスチェックは200', health.status, 200);
  checkString('問題6: ヘルスチェックの本文', health.body, '{"status":"ok"}');

  const detail = await request(baseUrl, '/api/products/3');
  checkString(
    '問題6: 商品1件の本文',
    detail.body,
    '{"id":3,"name":"マグカップ","price":2350,"stock":3,"categoryName":"キッチン雑貨"}'
  );

  const wrongMethod = await request(baseUrl, '/api/products/3', { method: 'DELETE' });
  checkNumber('問題6: メソッド違いは405', wrongMethod.status, 405);
  checkString('問題6: Allow ヘッダ', wrongMethod.allow, 'GET');

  const unknown = await request(baseUrl, '/api/orders');
  checkNumber('問題6: 知らないパスは404', unknown.status, 404);
} finally {
  await closeServer(routedServer);
}

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session20-practice: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session20-practice: ok');
