// セッション27「キャッシュ・パフォーマンス・ロギング」の検証スクリプト。
//
// キャッシュそのもの（Next.js のデータキャッシュ・フルルートキャッシュ）は
// web フォルダ側の機能なので、ここから import することはできない。
// ルートが静的か動的か、キャッシュが効いたかは、web の next build の出力と
// 実際のリクエストで確かめる（本文の第1節・第4節）。
//
// このファイルでは、Next.js に依存しない部分だけを検証する。
// 対応する web 側の実装は lib フォルダの logger.ts / cache-tags.ts / metrics.ts。
//
// 実行: docker compose exec ts npx tsx src/session27/verify.ts

import { randomUUID } from 'node:crypto';

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
    console.error(`NG: ${label} — 期待値 ${String(expected)} / 実際 ${String(actual)}`);
    failedCount += 1;
  }
}

function checkJson(label: string, actual: unknown, expected: unknown): void {
  checkString(label, JSON.stringify(actual), JSON.stringify(expected));
}

// ===========================================================================
// 本文9節：構造化ログ（web の lib/logger.ts と同じ実装）
// ===========================================================================
type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const LOG_LEVELS = ['debug', 'info', 'warn', 'error'] as const;

const LEVEL_SEVERITY: Record<LogLevel, number> = { debug: 10, info: 20, warn: 30, error: 40 };

const DEFAULT_LOG_LEVEL: LogLevel = 'info';

function parseLogLevel(raw: string | undefined): LogLevel {
  return LOG_LEVELS.find((level) => level === raw) ?? DEFAULT_LOG_LEVEL;
}

function shouldLog(configured: LogLevel, level: LogLevel): boolean {
  return LEVEL_SEVERITY[level] >= LEVEL_SEVERITY[configured];
}

// マスクの判定と置き換えは web の lib/security.ts（セッション26）にある。
// src からは import できないので、同じ仕様を書き写して検証する。
const REDACTED = '[REDACTED]';

const SENSITIVE_KEY_PARTS = [
  'password',
  'token',
  'secret',
  'authorization',
  'session',
  'cookie',
  'card',
  'cvv',
  'apikey',
  'api_key',
] as const;

function isSensitiveKey(key: string): boolean {
  const lowered = key.toLowerCase();

  return SENSITIVE_KEY_PARTS.some((part) => lowered.includes(part));
}

function maskSensitive(input: Record<string, unknown>): Record<string, unknown> {
  const masked: Record<string, unknown> = {};

  for (const [key, value] of Object.entries(input)) {
    masked[key] = isSensitiveKey(key) ? REDACTED : value;
  }

  return masked;
}

/** カード番号は下4桁だけ残す */
function maskCardNumber(raw: string): string {
  const digits = raw.replace(/\D/g, '');

  if (digits.length <= 4) {
    return '*'.repeat(digits.length);
  }

  return `${'*'.repeat(digits.length - 4)}${digits.slice(-4)}`;
}

/** 文章の中に紛れた秘密（Bearer トークン・長い数字の並び）を伏せる */
function maskTextSecrets(text: string): string {
  return text
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/g, `Bearer ${REDACTED}`)
    .replace(/\b\d{13,19}\b/g, (digits) => maskCardNumber(digits));
}

const RESERVED_KEYS = ['level', 'message', 'requestId', 'timestamp'] as const;

type LogFields = Record<string, unknown>;

function sanitizeFields(fields: LogFields): LogFields {
  const withoutReserved: LogFields = {};

  for (const [key, value] of Object.entries(fields)) {
    if ((RESERVED_KEYS as readonly string[]).includes(key)) {
      continue;
    }
    withoutReserved[key] = value;
  }

  return maskSensitive(withoutReserved);
}

type LogEntry = {
  level: LogLevel;
  message: string;
  requestId: string;
  timestamp: string;
  fields?: LogFields;
};

function buildLogLine(entry: LogEntry): string {
  return JSON.stringify({
    level: entry.level,
    // 例外のメッセージをそのまま渡されても、文章に紛れた秘密は伏せる
    message: maskTextSecrets(entry.message),
    requestId: entry.requestId,
    timestamp: entry.timestamp,
    ...sanitizeFields(entry.fields ?? {}),
  });
}

type Logger = {
  debug: (message: string, fields?: LogFields) => void;
  info: (message: string, fields?: LogFields) => void;
  warn: (message: string, fields?: LogFields) => void;
  error: (message: string, fields?: LogFields) => void;
};

type LoggerOptions = {
  requestId: string;
  minLevel: LogLevel;
  now: () => Date;
  write: (level: LogLevel, line: string) => void;
};

function createLogger(options: LoggerOptions): Logger {
  const log = (level: LogLevel, message: string, fields?: LogFields): void => {
    if (!shouldLog(options.minLevel, level)) {
      return;
    }

    options.write(
      level,
      buildLogLine({
        level,
        message,
        requestId: options.requestId,
        timestamp: options.now().toISOString(),
        fields,
      })
    );
  };

  return {
    debug: (message, fields) => log('debug', message, fields),
    info: (message, fields) => log('info', message, fields),
    warn: (message, fields) => log('warn', message, fields),
    error: (message, fields) => log('error', message, fields),
  };
}

// --- ログレベルの解釈 -------------------------------------------------------
const logLevelCases: { raw: string | undefined; expected: LogLevel }[] = [
  { raw: undefined, expected: 'info' },
  { raw: 'debug', expected: 'debug' },
  { raw: 'error', expected: 'error' },
  { raw: 'DEBUG', expected: 'info' },
  { raw: 'verbose', expected: 'info' },
  { raw: '', expected: 'info' },
];

for (const { raw, expected } of logLevelCases) {
  checkString(`本文9節: parseLogLevel(${JSON.stringify(raw)})`, parseLogLevel(raw), expected);
}

checkBoolean('本文9節: info 設定で debug は出さない', shouldLog('info', 'debug'), false);
checkBoolean('本文9節: info 設定で info は出す', shouldLog('info', 'info'), true);
checkBoolean('本文9節: info 設定で error は出す', shouldLog('info', 'error'), true);
checkBoolean('本文9節: debug 設定なら debug も出す', shouldLog('debug', 'debug'), true);
checkBoolean('本文9節: error 設定では warn を出さない', shouldLog('error', 'warn'), false);

// --- ログ1行の形 -----------------------------------------------------------
const FIXED_TIMESTAMP = '2026-08-29T12:00:00.000Z';
const FIXED_REQUEST_ID = '11111111-2222-3333-4444-555555555555';

const sampleLine = buildLogLine({
  level: 'info',
  message: '商品一覧を取得しました',
  requestId: FIXED_REQUEST_ID,
  timestamp: FIXED_TIMESTAMP,
  fields: { totalCount: 5, durationMs: 12.3 },
});

checkString(
  '本文9節: ログ1行は JSON（必須フィールドが先頭に並ぶ）',
  sampleLine,
  '{"level":"info","message":"商品一覧を取得しました",' +
    `"requestId":"${FIXED_REQUEST_ID}","timestamp":"${FIXED_TIMESTAMP}",` +
    '"totalCount":5,"durationMs":12.3}'
);
checkNumber('本文9節: ログは1行（改行を含まない）', sampleLine.split('\n').length, 1);

// JSON として読み直せることと、必須フィールドが揃っていることを確かめる
function hasRequiredLogFields(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) {
    return false;
  }

  return 'level' in value && 'message' in value && 'requestId' in value && 'timestamp' in value;
}

checkBoolean('本文9節: 必須フィールドが揃っている', hasRequiredLogFields(JSON.parse(sampleLine)), true);

// --- 機密のマスク（セッション18の方針をログにも適用する） -------------------
checkString(
  '本文9節: パスワードとトークンはマスクされる',
  buildLogLine({
    level: 'warn',
    message: 'ログインに失敗しました',
    requestId: FIXED_REQUEST_ID,
    timestamp: FIXED_TIMESTAMP,
    fields: {
      email: 'taro@example.com',
      password: 'p@ssw0rd',
      passwordHash: 'scrypt:...',
      sessionId: 'abc123',
      apiToken: 'tok_live_1',
      quantity: 2,
    },
  }),
  '{"level":"warn","message":"ログインに失敗しました",' +
    `"requestId":"${FIXED_REQUEST_ID}","timestamp":"${FIXED_TIMESTAMP}",` +
    '"email":"taro@example.com","password":"[REDACTED]","passwordHash":"[REDACTED]",' +
    '"sessionId":"[REDACTED]","apiToken":"[REDACTED]","quantity":2}'
);

checkBoolean('本文9節: 大文字でもマスクする', isSensitiveKey('Authorization'), true);
checkBoolean('本文9節: 部分一致でマスクする', isSensitiveKey('cardNumber'), true);
checkBoolean('本文9節: 関係ないキーはマスクしない', isSensitiveKey('categoryId'), false);
checkBoolean('本文9節: キャッシュキーはマスクしない', isSensitiveKey('cacheKey'), false);

// メッセージ本文に紛れた秘密も伏せる（セッション26の maskTextSecrets と同じ仕様）
checkString(
  '本文9節: メッセージ中のカード番号を伏せる',
  buildLogLine({
    level: 'error',
    message: 'カード 4242424242424242 の請求に失敗しました',
    requestId: FIXED_REQUEST_ID,
    timestamp: FIXED_TIMESTAMP,
  }),
  '{"level":"error","message":"カード ************4242 の請求に失敗しました",' +
    `"requestId":"${FIXED_REQUEST_ID}","timestamp":"${FIXED_TIMESTAMP}"}`
);
checkString(
  '本文9節: メッセージ中のトークンを伏せる',
  maskTextSecrets('Authorization: Bearer abc.def-123 が拒否されました'),
  'Authorization: Bearer [REDACTED] が拒否されました'
);

checkString(
  '本文9節: 予約フィールドは追加情報で壊されない',
  buildLogLine({
    level: 'info',
    message: '本来のメッセージ',
    requestId: FIXED_REQUEST_ID,
    timestamp: FIXED_TIMESTAMP,
    fields: { level: 'error', message: '偽のメッセージ', productId: 3 },
  }),
  '{"level":"info","message":"本来のメッセージ",' +
    `"requestId":"${FIXED_REQUEST_ID}","timestamp":"${FIXED_TIMESTAMP}","productId":3}`
);

// --- ロガーの出力（出力先と時刻を注入して確かめる） -------------------------
const written: string[] = [];
const logger = createLogger({
  requestId: FIXED_REQUEST_ID,
  minLevel: 'info',
  now: () => new Date(FIXED_TIMESTAMP),
  write: (_level, logLine) => {
    written.push(logLine);
  },
});

logger.debug('これは出ない');
logger.info('在庫を引き当てました', { productId: 3, quantity: 2 });
logger.error('決済に失敗しました', { orderId: 'order-1', cardNumber: '4242424242424242' });

checkNumber('本文9節: info 設定なので debug の1件は出ない', written.length, 2);
checkString(
  '本文9節: info の1行',
  written[0] ?? '(出力なし)',
  '{"level":"info","message":"在庫を引き当てました",' +
    `"requestId":"${FIXED_REQUEST_ID}","timestamp":"${FIXED_TIMESTAMP}",` +
    '"productId":3,"quantity":2}'
);
checkString(
  '本文9節: error でもカード番号は残らない',
  written[1] ?? '(出力なし)',
  '{"level":"error","message":"決済に失敗しました",' +
    `"requestId":"${FIXED_REQUEST_ID}","timestamp":"${FIXED_TIMESTAMP}",` +
    '"orderId":"order-1","cardNumber":"[REDACTED]"}'
);

// ===========================================================================
// 本文9節：リクエストIDの生成と伝播
// React の cache() は「同じリクエストの中では1回だけ実行する」。
// ここではその性質を、リクエストごとの入れ物（スコープ）で再現して確かめる。
// ===========================================================================
function createRequestScope(): { getRequestId: () => string } {
  let requestId: string | undefined;

  return {
    getRequestId: () => {
      requestId ??= randomUUID();

      return requestId;
    },
  };
}

const requestA = createRequestScope();
const requestB = createRequestScope();

const firstInA = requestA.getRequestId();
const secondInA = requestA.getRequestId();

checkBoolean('本文9節: 同じリクエストの中では同じID', firstInA === secondInA, true);
checkBoolean('本文9節: 別のリクエストでは違うID', firstInA === requestB.getRequestId(), false);
checkNumber('本文9節: リクエストIDの長さ（UUID）', firstInA.length, 36);
checkBoolean(
  '本文9節: リクエストIDの形（16進数とハイフン）',
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(firstInA),
  true
);

// 1000回作って全部違うことを確かめる（衝突すると別のリクエストのログが混ざる）
const generated = new Set<string>();

for (let index = 0; index < 1000; index += 1) {
  generated.add(createRequestScope().getRequestId());
}
checkNumber('本文9節: 1000件のリクエストIDが重複しない', generated.size, 1000);

// ===========================================================================
// 本文2節：静的レンダリングと動的レンダリングの分岐（本文の表と同じ判定）
// ===========================================================================
type DynamicConfig = 'auto' | 'force-dynamic' | 'force-static';

type RouteSignals = {
  // cookies() / headers() を読んでいるか（レイアウトの中で読んでいる場合も含む）
  readsCookiesOrHeaders: boolean;
  // searchParams を読んでいるか
  readsSearchParams: boolean;
  // cache: 'no-store' を明示した fetch があるか
  hasExplicitNoStoreFetch: boolean;
  dynamicConfig: DynamicConfig;
};

type RenderingDecision = { kind: 'static' } | { kind: 'dynamic'; reason: string };

function decideRendering(signals: RouteSignals): RenderingDecision {
  // force-static は他のすべてに勝つ。cookies() は空の値を返すようになる
  if (signals.dynamicConfig === 'force-static') {
    return { kind: 'static' };
  }
  if (signals.dynamicConfig === 'force-dynamic') {
    return { kind: 'dynamic', reason: "dynamic = 'force-dynamic' の指定" };
  }
  if (signals.readsCookiesOrHeaders) {
    return { kind: 'dynamic', reason: 'cookies() / headers() の読み取り' };
  }
  if (signals.readsSearchParams) {
    return { kind: 'dynamic', reason: 'searchParams の読み取り' };
  }
  if (signals.hasExplicitNoStoreFetch) {
    return { kind: 'dynamic', reason: "cache: 'no-store' の fetch" };
  }

  return { kind: 'static' };
}

function describeDecision(decision: RenderingDecision): string {
  return decision.kind === 'static' ? 'static' : `dynamic:${decision.reason}`;
}

const AUTO_STATIC: RouteSignals = {
  readsCookiesOrHeaders: false,
  readsSearchParams: false,
  hasExplicitNoStoreFetch: false,
  dynamicConfig: 'auto',
};

checkString('本文2節: 何も読まなければ静的', describeDecision(decideRendering(AUTO_STATIC)), 'static');
checkString(
  '本文2節: レイアウトが Cookie を読むと動的',
  describeDecision(decideRendering({ ...AUTO_STATIC, readsCookiesOrHeaders: true })),
  'dynamic:cookies() / headers() の読み取り'
);
checkString(
  '本文2節: searchParams を読むと動的',
  describeDecision(decideRendering({ ...AUTO_STATIC, readsSearchParams: true })),
  'dynamic:searchParams の読み取り'
);
checkString(
  '本文2節: no-store の fetch でも動的',
  describeDecision(decideRendering({ ...AUTO_STATIC, hasExplicitNoStoreFetch: true })),
  "dynamic:cache: 'no-store' の fetch"
);
checkString(
  '本文2節: force-dynamic は宣言だけで動的',
  describeDecision(decideRendering({ ...AUTO_STATIC, dynamicConfig: 'force-dynamic' })),
  "dynamic:dynamic = 'force-dynamic' の指定"
);
checkString(
  '本文2節: force-static なら Cookie を読んでいても静的',
  describeDecision(
    decideRendering({ ...AUTO_STATIC, readsCookiesOrHeaders: true, dynamicConfig: 'force-static' })
  ),
  'static'
);
checkString(
  '本文2節: force-dynamic を消しても searchParams があれば動的のまま',
  describeDecision(decideRendering({ ...AUTO_STATIC, readsSearchParams: true })),
  'dynamic:searchParams の読み取り'
);

// ===========================================================================
// 本文4節：キャッシュキーとタグ（web の lib/cache-tags.ts と同じ実装）
// ===========================================================================
type SortKey = 'price-asc' | 'price-desc' | 'name-asc';

const PRODUCTS_TAG = 'products';
const CATEGORIES_TAG = 'categories';

function productTag(productId: number): string {
  return `product-${productId}`;
}

function categoryTag(slug: string): string {
  return `category-${slug}`;
}

type ProductUpdateTarget = {
  productId: number;
  categorySlug: string;
  previousCategorySlug: string | null;
};

function tagsForProductUpdate(target: ProductUpdateTarget): string[] {
  const tags = [PRODUCTS_TAG, productTag(target.productId), categoryTag(target.categorySlug)];

  if (target.previousCategorySlug !== null) {
    tags.push(categoryTag(target.previousCategorySlug));
  }

  return [...new Set(tags)];
}

type ProductListCacheInput = {
  categoryId: number | null;
  keyword: string;
  sort: SortKey;
  page: number;
};

function buildProductListCacheKey(input: ProductListCacheInput): string {
  const category = input.categoryId === null ? 'all' : String(input.categoryId);
  const keyword = input.keyword.trim().toLowerCase();

  return [
    'products',
    `category=${category}`,
    `keyword=${keyword}`,
    `sort=${input.sort}`,
    `page=${input.page}`,
  ].join(':');
}

checkString(
  '本文4節: 条件なしのキー',
  buildProductListCacheKey({ categoryId: null, keyword: '', sort: 'price-asc', page: 1 }),
  'products:category=all:keyword=:sort=price-asc:page=1'
);
checkString(
  '本文4節: カテゴリと検索語のあるキー',
  buildProductListCacheKey({ categoryId: 1, keyword: '石けん', sort: 'name-asc', page: 2 }),
  'products:category=1:keyword=石けん:sort=name-asc:page=2'
);

// 「書いた順番が違うだけ」の条件は同じキーになる（キャッシュが無駄に増えないため）
checkString(
  '本文4節: プロパティの順番が違っても同じキー',
  buildProductListCacheKey({ page: 2, sort: 'name-asc', keyword: '石けん', categoryId: 1 }),
  buildProductListCacheKey({ categoryId: 1, keyword: '石けん', sort: 'name-asc', page: 2 })
);
// 空白と大文字小文字の違いも吸収する
checkString(
  '本文4節: キーワードの前後の空白と大文字小文字は吸収する',
  buildProductListCacheKey({ categoryId: null, keyword: '  SOAP ', sort: 'price-asc', page: 1 }),
  buildProductListCacheKey({ categoryId: null, keyword: 'soap', sort: 'price-asc', page: 1 })
);
// 条件が違えば別のキーになる（違う結果が同じキーに入ると事故になる）
checkBoolean(
  '本文4節: ページが違えば別のキー',
  buildProductListCacheKey({ categoryId: null, keyword: '', sort: 'price-asc', page: 1 }) ===
    buildProductListCacheKey({ categoryId: null, keyword: '', sort: 'price-asc', page: 2 }),
  false
);
checkBoolean(
  '本文4節: 並べ替えが違えば別のキー',
  buildProductListCacheKey({ categoryId: 1, keyword: '', sort: 'price-asc', page: 1 }) ===
    buildProductListCacheKey({ categoryId: 1, keyword: '', sort: 'price-desc', page: 1 }),
  false
);

checkJson(
  '本文4節: 商品を更新したら捨てるタグ（カテゴリ移動なし）',
  tagsForProductUpdate({ productId: 3, categorySlug: 'kitchen', previousCategorySlug: null }),
  ['products', 'product-3', 'category-kitchen']
);
checkJson(
  '本文4節: カテゴリを移動したら移動元も捨てる',
  tagsForProductUpdate({ productId: 3, categorySlug: 'fabric', previousCategorySlug: 'kitchen' }),
  ['products', 'product-3', 'category-fabric', 'category-kitchen']
);
checkJson(
  '本文4節: 移動前と移動後が同じなら重複しない',
  tagsForProductUpdate({ productId: 5, categorySlug: 'fabric', previousCategorySlug: 'fabric' }),
  ['products', 'product-5', 'category-fabric']
);
checkString('本文4節: カテゴリ一覧のタグ', CATEGORIES_TAG, 'categories');

// ===========================================================================
// 本文5節：TTL 付きのキャッシュを自分で作る
// 時刻は引数で受け取る（実時間に依存させないため）。
// ===========================================================================
type CacheStats = { hits: number; misses: number; expired: number };

type TtlCache<T> = {
  get: (key: string, now: number) => T | undefined;
  set: (key: string, value: T, now: number, tags?: readonly string[]) => void;
  invalidateTag: (tag: string) => number;
  size: () => number;
  stats: () => CacheStats;
};

function createTtlCache<T>(ttlMs: number): TtlCache<T> {
  type Entry = { value: T; expiresAt: number; tags: readonly string[] };

  const store = new Map<string, Entry>();
  const counts: CacheStats = { hits: 0, misses: 0, expired: 0 };

  return {
    get: (key, now) => {
      const entry = store.get(key);

      if (entry === undefined) {
        counts.misses += 1;

        return undefined;
      }
      // 期限が来ていたら捨てる。境界（ちょうど期限の瞬間）は切れている扱い
      if (entry.expiresAt <= now) {
        store.delete(key);
        counts.expired += 1;
        counts.misses += 1;

        return undefined;
      }
      counts.hits += 1;

      return entry.value;
    },
    set: (key, value, now, tags = []) => {
      store.set(key, { value, expiresAt: now + ttlMs, tags });
    },
    invalidateTag: (tag) => {
      let deleted = 0;

      for (const [key, entry] of store) {
        if (entry.tags.includes(tag)) {
          store.delete(key);
          deleted += 1;
        }
      }

      return deleted;
    },
    size: () => store.size,
    stats: () => ({ ...counts }),
  };
}

const TTL_MS = 60_000;
const cache = createTtlCache<number>(TTL_MS);
const T0 = 1_000_000;

checkBoolean('本文5節: 最初はミス', cache.get('products:page=1', T0) === undefined, true);

cache.set('products:page=1', 5, T0, [PRODUCTS_TAG, categoryTag('kitchen')]);

checkNumber('本文5節: 保存直後は当たる', cache.get('products:page=1', T0 + 1) ?? -1, 5);
checkNumber('本文5節: 期限の直前は当たる', cache.get('products:page=1', T0 + TTL_MS - 1) ?? -1, 5);
checkBoolean(
  '本文5節: 期限ちょうどは切れている',
  cache.get('products:page=1', T0 + TTL_MS) === undefined,
  true
);
checkNumber('本文5節: 期限切れの記録は捨てられる', cache.size(), 0);
checkJson('本文5節: ヒット・ミス・期限切れの数', cache.stats(), {
  hits: 2,
  misses: 2,
  expired: 1,
});

// タグでまとめて捨てる（revalidateTag がやっていること）
const tagged = createTtlCache<string>(TTL_MS);

tagged.set('products:page=1', 'ページ1', T0, [PRODUCTS_TAG, categoryTag('kitchen')]);
tagged.set('products:page=2', 'ページ2', T0, [PRODUCTS_TAG, categoryTag('fabric')]);
tagged.set('categories:all', 'カテゴリ', T0, [CATEGORIES_TAG]);

checkNumber('本文5節: 3件保存されている', tagged.size(), 3);
checkNumber('本文5節: kitchen のタグで1件だけ捨てる', tagged.invalidateTag(categoryTag('kitchen')), 1);
checkNumber('本文5節: 残りは2件', tagged.size(), 2);
checkNumber('本文5節: products のタグで残りの一覧を捨てる', tagged.invalidateTag(PRODUCTS_TAG), 1);
checkBoolean(
  '本文5節: カテゴリのキャッシュは残っている',
  tagged.get('categories:all', T0 + 1) === 'カテゴリ',
  true
);
checkNumber('本文5節: 無いタグを捨てても0件', tagged.invalidateTag('product-999'), 0);

// キャッシュを通してデータを読む（同じ条件なら DB は1回しか呼ばれない）
async function loadThroughCache(
  target: TtlCache<number>,
  key: string,
  now: number,
  load: () => Promise<number>
): Promise<number> {
  const cached = target.get(key, now);

  if (cached !== undefined) {
    return cached;
  }

  const value = await load();

  target.set(key, value, now, [PRODUCTS_TAG]);

  return value;
}

const readThrough = createTtlCache<number>(TTL_MS);
let loadCount = 0;
const loadFromDb = async (): Promise<number> => {
  loadCount += 1;

  return 5;
};
const key = buildProductListCacheKey({ categoryId: null, keyword: '', sort: 'price-asc', page: 1 });

checkNumber(
  '本文5節: 1回目はデータベースを見る',
  await loadThroughCache(readThrough, key, T0, loadFromDb),
  5
);
checkNumber(
  '本文5節: 2回目はキャッシュから返る',
  await loadThroughCache(readThrough, key, T0 + 10, loadFromDb),
  5
);
checkNumber('本文5節: データベースの呼び出しは1回だけ', loadCount, 1);

await loadThroughCache(readThrough, key, T0 + TTL_MS, loadFromDb);
checkNumber('本文5節: 期限が切れたらもう一度データベースを見る', loadCount, 2);

// ===========================================================================
// 本文7節：取得件数を絞ると転送量がどれだけ減るか（web の lib/metrics.ts と同じ実装）
// ===========================================================================
function estimateTransferBytes(
  itemCount: number,
  bytesPerItem: number,
  overheadBytes: number
): number {
  return itemCount * bytesPerItem + overheadBytes;
}

function savedRatioPercent(beforeBytes: number, afterBytes: number): number {
  if (beforeBytes <= 0) {
    return 0;
  }

  return Math.round((1 - afterBytes / beforeBytes) * 100);
}

// 比較のための仮の数字（実際の値は自分の環境で測る）。
// 一覧に必要な6列だけなら1件あたり 120 バイト、description まで含めると 320 バイト。
const BYTES_PER_SUMMARY = 120;
const BYTES_PER_DETAIL = 320;
const OVERHEAD_BYTES = 200;

// 商品が200件あるカタログで、全件返す場合と1ページ分（3件）だけ返す場合
const allDetail = estimateTransferBytes(200, BYTES_PER_DETAIL, OVERHEAD_BYTES);
const onePageDetail = estimateTransferBytes(3, BYTES_PER_DETAIL, OVERHEAD_BYTES);
const onePageSummary = estimateTransferBytes(3, BYTES_PER_SUMMARY, OVERHEAD_BYTES);

checkNumber('本文7節: 全件を詳細で返すと', allDetail, 64_200);
checkNumber('本文7節: 1ページ分（3件）だけなら', onePageDetail, 1_160);
checkNumber(
  '本文7節: ページ送りだけで削減できる割合',
  savedRatioPercent(allDetail, onePageDetail),
  98
);
checkNumber('本文7節: 必要な列だけにすると', onePageSummary, 560);
checkNumber(
  '本文7節: 1ページ分のうち列を絞って削減できる割合',
  savedRatioPercent(onePageDetail, onePageSummary),
  52
);
checkNumber('本文7節: 0件のときは0%', savedRatioPercent(0, 0), 0);

// ===========================================================================
// 本文10節：Core Web Vitals のしきい値判定（web の lib/metrics.ts と同じ実装）
// ===========================================================================
type WebVitalName = 'LCP' | 'INP' | 'CLS';
type WebVitalRating = 'good' | 'needs-improvement' | 'poor';

const WEB_VITAL_THRESHOLDS: Record<WebVitalName, { good: number; poor: number }> = {
  LCP: { good: 2500, poor: 4000 },
  INP: { good: 200, poor: 500 },
  CLS: { good: 0.1, poor: 0.25 },
};

function rateWebVital(name: WebVitalName, value: number): WebVitalRating {
  const threshold = WEB_VITAL_THRESHOLDS[name];

  if (value <= threshold.good) {
    return 'good';
  }
  if (value <= threshold.poor) {
    return 'needs-improvement';
  }

  return 'poor';
}

function rateOverall(ratings: readonly WebVitalRating[]): WebVitalRating {
  if (ratings.includes('poor')) {
    return 'poor';
  }
  if (ratings.includes('needs-improvement')) {
    return 'needs-improvement';
  }

  return 'good';
}

const vitalCases: { name: WebVitalName; value: number; expected: WebVitalRating }[] = [
  { name: 'LCP', value: 1800, expected: 'good' },
  { name: 'LCP', value: 2500, expected: 'good' },
  { name: 'LCP', value: 2501, expected: 'needs-improvement' },
  { name: 'LCP', value: 4000, expected: 'needs-improvement' },
  { name: 'LCP', value: 4001, expected: 'poor' },
  { name: 'INP', value: 120, expected: 'good' },
  { name: 'INP', value: 200, expected: 'good' },
  { name: 'INP', value: 350, expected: 'needs-improvement' },
  { name: 'INP', value: 500, expected: 'needs-improvement' },
  { name: 'INP', value: 900, expected: 'poor' },
  { name: 'CLS', value: 0, expected: 'good' },
  { name: 'CLS', value: 0.1, expected: 'good' },
  { name: 'CLS', value: 0.2, expected: 'needs-improvement' },
  { name: 'CLS', value: 0.25, expected: 'needs-improvement' },
  { name: 'CLS', value: 0.4, expected: 'poor' },
];

for (const { name, value, expected } of vitalCases) {
  checkString(`本文10節: rateWebVital('${name}', ${value})`, rateWebVital(name, value), expected);
}

checkString(
  '本文10節: 3つとも良好なら good',
  rateOverall([rateWebVital('LCP', 1800), rateWebVital('INP', 120), rateWebVital('CLS', 0.05)]),
  'good'
);
checkString(
  '本文10節: 1つでも poor があれば poor',
  rateOverall([rateWebVital('LCP', 1800), rateWebVital('INP', 900), rateWebVital('CLS', 0.05)]),
  'poor'
);
checkString(
  '本文10節: poor が無く改善が必要なものがあれば needs-improvement',
  rateOverall([rateWebVital('LCP', 3000), rateWebVital('INP', 120), rateWebVital('CLS', 0.05)]),
  'needs-improvement'
);

// ===========================================================================
// 本文7節：Server-Timing ヘッダの値（web の lib/metrics.ts と同じ実装）
// ===========================================================================
type TimingEntry = { name: string; durationMs: number };

function roundMs(value: number): number {
  return Math.round(value * 10) / 10;
}

function formatServerTiming(entries: readonly TimingEntry[]): string {
  return entries.map((entry) => `${entry.name};dur=${roundMs(entry.durationMs)}`).join(', ');
}

checkNumber('本文7節: ミリ秒は小数第1位に丸める', roundMs(12.345678), 12.3);
checkString(
  '本文7節: Server-Timing の値',
  formatServerTiming([
    { name: 'db', durationMs: 12.345 },
    { name: 'render', durationMs: 4.5 },
  ]),
  'db;dur=12.3, render;dur=4.5'
);
checkString('本文7節: 測定が無いときは空文字列', formatServerTiming([]), '');

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session27: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session27: ok');
