// セッション20「WebとHTTPの基礎・Node.jsサーバー」の検証スクリプト。
//
// 本文（074）と練習問題の解答（076）に載せたコードを実際に動かし、
// 章に書いた「期待される出力」と一致するかを確認する。
//
// HTTP サーバーは OS が選んだ空きポートで起動し、検証が終わったら必ず停止する。
// 相手は自分で立てたサーバーだけで、外部のネットワークには一切アクセスしない。
//
// 実行: docker compose exec ts npx tsx src/session20/verify.ts

import { createServer } from 'node:http';
import type { CatalogItem } from '../session17/catalog';
import type { ShopError } from '../session18/shop';
import { toErrorPayload, toHttpStatus } from './error-status';
import { createHelloServer } from './hello-server';
import { buildSetCookieHeader, parseCookieHeader, withErrorHandling } from './http-tools';
import { formatResponse } from './response-format';
import { closeServer, listenOnRandomPort } from './server-utils';
import { createShopServer, isAddToCartBody, matchProductId } from './shop-server';
import { formatUrlParts } from './url-parts';

// ---------------------------------------------------------------------------
// 検証ヘルパー（期待値と違えば失敗として記録する）
// ---------------------------------------------------------------------------
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

function checkBoolean(label: string, actual: boolean, expected: boolean): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 ${expected} / 実際 ${actual}`);
    failedCount += 1;
  }
}

// ---------------------------------------------------------------------------
// HTTP クライアント（fetch の薄い包み）
// ---------------------------------------------------------------------------
type RequestOptions = {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
};

type Fetched = {
  status: number;
  contentType: string;
  allow: string;
  body: string;
};

async function request(
  baseUrl: string,
  path: string,
  options: RequestOptions = {}
): Promise<Fetched> {
  // fetch は既定でリダイレクト（3xx）を自動で追いかける
  const res = await fetch(`${baseUrl}${path}`, options);

  return {
    status: res.status,
    contentType: res.headers.get('content-type') ?? '(なし)',
    allow: res.headers.get('allow') ?? '(なし)',
    body: await res.text(),
  };
}

function postJson(payload: unknown): RequestOptions {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  };
}

// ---------------------------------------------------------------------------
// 本文 1節：URL の構造
// ---------------------------------------------------------------------------
checkString(
  '本文1節: URL を部品に分解する',
  formatUrlParts('https://shop.example.com:8443/products/3?color=blue&size=m#reviews'),
  'protocol: https:\n' +
    'hostname: shop.example.com\n' +
    'port: 8443\n' +
    'pathname: /products/3\n' +
    'search: ?color=blue&size=m\n' +
    'hash: #reviews'
);

checkString(
  '本文1節: ポートを省略した URL',
  formatUrlParts('https://shop.example.com/products'),
  'protocol: https:\n' +
    'hostname: shop.example.com\n' +
    'port: (既定値)\n' +
    'pathname: /products\n' +
    'search: (なし)\n' +
    'hash: (なし)'
);

// ---------------------------------------------------------------------------
// 本文 2節：最初のサーバー
// ---------------------------------------------------------------------------
const helloServer = createHelloServer();

try {
  const port = await listenOnRandomPort(helloServer);
  const baseUrl = `http://127.0.0.1:${port}`;

  const top = await request(baseUrl, '/');
  checkNumber('本文2節: ステータスコードは200', top.status, 200);
  checkString('本文2節: Content-Type', top.contentType, 'text/plain; charset=utf-8');
  checkString('本文2節: 本文', top.body, 'Hello, ミニ雑貨ショップ!\nmethod=GET path=/\n');

  const other = await request(baseUrl, '/products?q=soap');
  checkString(
    '本文2節: どのパスでも同じ形で返る',
    other.body,
    'Hello, ミニ雑貨ショップ!\nmethod=GET path=/products\n'
  );

  const posted = await request(baseUrl, '/', postJson({ any: 'thing' }));
  checkString(
    '本文2節: メソッドが変わっても同じ処理に来る',
    posted.body,
    'Hello, ミニ雑貨ショップ!\nmethod=POST path=/\n'
  );
} finally {
  await closeServer(helloServer);
}

// ---------------------------------------------------------------------------
// 本文 4節：Result の失敗をステータスコードに写す
// ---------------------------------------------------------------------------
const invalidQuantity: ShopError = { kind: 'invalid_quantity', input: 'abc' };
const outOfRange: ShopError = { kind: 'quantity_out_of_range', value: 20 };
const notFound: ShopError = { kind: 'product_not_found', productId: 99 };
const outOfStock: ShopError = {
  kind: 'out_of_stock',
  productName: 'リネンのふきん',
  requested: 1,
  available: 0,
};
const catalogDown: ShopError = {
  kind: 'catalog_unavailable',
  reason: '/work/fixtures/products.json が読めません',
};
const shopErrors: readonly ShopError[] = [
  invalidQuantity,
  outOfRange,
  notFound,
  outOfStock,
  catalogDown,
];

checkString(
  '本文4節: ShopError とステータスコードの対応',
  shopErrors.map((error) => `${error.kind} → ${toHttpStatus(error)}`).join('\n'),
  'invalid_quantity → 400\n' +
    'quantity_out_of_range → 400\n' +
    'product_not_found → 404\n' +
    'out_of_stock → 409\n' +
    'catalog_unavailable → 503'
);

checkString(
  '本文4節: 4xx はそのまま理由を返す',
  JSON.stringify(toErrorPayload(notFound)),
  '{"error":{"kind":"product_not_found","message":"商品が見つかりません（productId: 99）"}}'
);

checkString(
  '本文4節: 5xx は内部の事情を外に出さない',
  JSON.stringify(toErrorPayload(catalogDown)),
  '{"error":{"kind":"catalog_unavailable",' +
    '"message":"サーバー側の問題でリクエストを処理できませんでした"}}'
);

checkBoolean(
  '本文4節: 5xx の本文にファイルパスが含まれない',
  JSON.stringify(toErrorPayload(catalogDown)).includes('products.json'),
  false
);

// ---------------------------------------------------------------------------
// 本文 5節：ヘッダと Cookie
// ---------------------------------------------------------------------------
checkString(
  '本文5節: Set-Cookie の組み立て',
  buildSetCookieHeader('shop_session', 'abc123'),
  'shop_session=abc123; Path=/; Max-Age=3600; HttpOnly; Secure; SameSite=Lax'
);

const cookies = parseCookieHeader('shop_session=abc123; theme=dark');
checkNumber('本文5節: Cookie は2件', cookies.size, 2);
checkString(
  '本文5節: Cookie ヘッダの解析',
  `${cookies.get('shop_session') ?? '(なし)'} / ${cookies.get('theme') ?? '(なし)'}`,
  'abc123 / dark'
);
checkNumber('本文5節: Cookie ヘッダが無ければ0件', parseCookieHeader(undefined).size, 0);

checkString(
  '本文5節: curl -i と同じ形に整形する',
  formatResponse(
    200,
    'OK',
    ['content-type: application/json; charset=utf-8', 'content-length: 11'],
    '{"count":5}'
  ),
  'HTTP/1.1 200 OK\n' +
    'content-length: 11\n' +
    'content-type: application/json; charset=utf-8\n' +
    '\n' +
    '{"count":5}'
);

// ---------------------------------------------------------------------------
// 本文 7節：ルーティングの部品
// ---------------------------------------------------------------------------
checkString(
  '本文7節: パスから商品IDを取り出す',
  ['/api/products/3', '/api/products/999', '/api/products/abc', '/api/products']
    .map((path) => {
      const id = matchProductId(path);
      return `${path} → ${id === undefined ? '(一致しない)' : id}`;
    })
    .join('\n'),
  '/api/products/3 → 3\n' +
    '/api/products/999 → 999\n' +
    '/api/products/abc → (一致しない)\n' +
    '/api/products → (一致しない)'
);

checkString(
  '本文7節: ボディの型ガード',
  [
    isAddToCartBody({ productId: 1, quantityInput: '2' }),
    isAddToCartBody({ productId: 1 }),
    isAddToCartBody({ productId: '1', quantityInput: '2' }),
    isAddToCartBody(null),
  ]
    .map((value) => String(value))
    .join(' / '),
  'true / false / false / false'
);

// ---------------------------------------------------------------------------
// 本文 7節：ショップの API サーバー
// ---------------------------------------------------------------------------
const shopServer = createShopServer({
  onError: () => {
    // 検証中はログを出さない（依存を引数で受け取る設計にしてあるので差し替えられる）
  },
});

try {
  const port = await listenOnRandomPort(shopServer);
  const baseUrl = `http://127.0.0.1:${port}`;

  const all = await request(baseUrl, '/api/products');
  checkNumber('本文7節: 一覧は200', all.status, 200);
  checkString('本文7節: 一覧の Content-Type', all.contentType, 'application/json; charset=utf-8');
  checkBoolean('本文7節: 一覧は5件', all.body.startsWith('{"count":5,'), true);

  const filtered = await request(baseUrl, '/api/products?q=石けん');
  checkString(
    '本文7節: クエリで絞り込む',
    filtered.body,
    '{"count":1,"items":[{"id":1,"name":"ラベンダーの石けん","price":480,"stock":24,' +
      '"categoryName":"バス・ボディケア"}]}'
  );

  const detail = await request(baseUrl, '/api/products/3');
  checkNumber('本文7節: 商品1件は200', detail.status, 200);
  checkString(
    '本文7節: 商品1件の本文',
    detail.body,
    '{"id":3,"name":"マグカップ","price":2350,"stock":3,"categoryName":"キッチン雑貨"}'
  );

  const missing = await request(baseUrl, '/api/products/999');
  checkNumber('本文7節: 無い商品は404', missing.status, 404);
  checkString(
    '本文7節: 404 の本文',
    missing.body,
    '{"error":{"kind":"product_not_found","message":"商品が見つかりません（productId: 999）"}}'
  );

  const wrongPath = await request(baseUrl, '/api/products/abc');
  checkNumber('本文7節: 数字でないIDはルート不一致の404', wrongPath.status, 404);
  checkString(
    '本文7節: ルート不一致の本文',
    wrongPath.body,
    '{"error":{"kind":"route_not_found","message":"そのURLはありません: GET /api/products/abc"}}'
  );

  const wrongMethod = await request(baseUrl, '/api/products', { method: 'DELETE' });
  checkNumber('本文7節: 使えないメソッドは405', wrongMethod.status, 405);
  checkString('本文7節: Allow ヘッダ', wrongMethod.allow, 'GET');
  checkString(
    '本文7節: 405 の本文',
    wrongMethod.body,
    '{"error":{"kind":"method_not_allowed","message":"このURLでは GET だけを使えます"}}'
  );

  // fetch は 301 を自動で追いかけるので、届くのはリダイレクト先のレスポンス
  const redirected = await request(baseUrl, '/products');
  checkNumber('本文7節: 旧URLはリダイレクト先が返る', redirected.status, 200);
  checkBoolean('本文7節: リダイレクト先は商品一覧', redirected.body.startsWith('{"count":5,'), true);

  const created = await request(baseUrl, '/api/cart', postJson({ productId: 1, quantityInput: '2' }));
  checkNumber('本文7節: カート追加は201', created.status, 201);
  checkString(
    '本文7節: 201 の本文',
    created.body,
    '{"productId":1,"productName":"ラベンダーの石けん","quantity":2,"lineTotal":960}'
  );

  const badQuantity = await request(
    baseUrl,
    '/api/cart',
    postJson({ productId: 1, quantityInput: '0' })
  );
  checkNumber('本文7節: 範囲外の数量は400', badQuantity.status, 400);
  checkString(
    '本文7節: 400 の本文',
    badQuantity.body,
    '{"error":{"kind":"quantity_out_of_range",' +
      '"message":"数量は1以上10以下で指定してください（受け取った値: 0）"}}'
  );

  const soldOut = await request(baseUrl, '/api/cart', postJson({ productId: 4, quantityInput: '1' }));
  checkNumber('本文7節: 在庫不足は409', soldOut.status, 409);
  checkString(
    '本文7節: 409 の本文',
    soldOut.body,
    '{"error":{"kind":"out_of_stock",' +
      '"message":"リネンのふきんの在庫が足りません（希望 1点 / 在庫 0点）"}}'
  );

  const brokenJson = await request(baseUrl, '/api/cart', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: 'not json',
  });
  checkNumber('本文7節: 壊れた JSON は400', brokenJson.status, 400);
  checkString(
    '本文7節: 壊れた JSON の本文',
    brokenJson.body,
    '{"error":{"kind":"invalid_json",' +
      '"message":"リクエストボディを JSON として読めませんでした"}}'
  );

  const missingField = await request(baseUrl, '/api/cart', postJson({ productId: 1 }));
  checkNumber('本文7節: 項目が足りないボディは400', missingField.status, 400);
  checkString(
    '本文7節: 項目不足の本文',
    missingField.body,
    '{"error":{"kind":"invalid_body",' +
      '"message":"productId（数値）と quantityInput（文字列）が必要です"}}'
  );

  const unknownPath = await request(baseUrl, '/api/orders');
  checkNumber('本文7節: 知らないパスは404', unknownPath.status, 404);
} finally {
  await closeServer(shopServer);
}

// ---------------------------------------------------------------------------
// 本文 4節・8節：5xx の2種類（503 と 500）
// ---------------------------------------------------------------------------
const brokenLoader = (): Promise<CatalogItem[]> => {
  throw new Error('products.json を読めません');
};

const brokenServer = createShopServer({ onError: () => {}, loadCatalog: brokenLoader });

try {
  const port = await listenOnRandomPort(brokenServer);
  const response = await request(`http://127.0.0.1:${port}`, '/api/products');

  checkNumber('本文4節: カタログが読めないときは503', response.status, 503);
  checkString(
    '本文4節: 503 の本文',
    response.body,
    '{"error":{"kind":"catalog_unavailable",' +
      '"message":"サーバー側の問題でリクエストを処理できませんでした"}}'
  );
} finally {
  await closeServer(brokenServer);
}

const crashServer = createServer(
  withErrorHandling(
    async () => {
      throw new Error('わざと失敗させた処理');
    },
    () => {
      // 検証中はログを出さない
    }
  )
);

try {
  const port = await listenOnRandomPort(crashServer);
  const response = await request(`http://127.0.0.1:${port}`, '/');

  checkNumber('本文8節: 想定外の例外は500になる', response.status, 500);
  checkString(
    '本文8節: 500 の本文',
    response.body,
    '{"error":{"kind":"internal_error","message":"サーバー内部でエラーが発生しました"}}'
  );
} finally {
  await closeServer(crashServer);
}

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session20: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session20: ok');
