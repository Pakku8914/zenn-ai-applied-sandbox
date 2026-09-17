// セッション26「Webアプリケーションのセキュリティ」の検証スクリプト。
//
// この章の実装は web フォルダ側（lib/security.ts・lib/env.ts・middleware.ts・
// app/api/orders/[id]/route.ts）にあり、src 側からは import できない。
// ただし章の中身はほとんどが「引数だけで結果が決まる判定」なので、
// 同じ実装をここで動かして確かめられる。
//
// 防御のコードは「動いた」では正しさが分からない。エスケープを忘れても
// 画面は普通に出るし、認可が抜けていてもエラーは出ない。だから
// 「守れていること」ではなく「守れていないことを検出できること」まで確かめる。
//
// 実行: docker compose exec ts npx tsx src/session26/verify.ts

import { randomBytes } from 'node:crypto';
import { z } from 'zod';

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

// ---------------------------------------------------------------------------
// 本文3節：HTML エスケープ（web の lib/security.ts と同じ実装）
// ---------------------------------------------------------------------------

function escapeHtml(input: string): string {
  return input
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

/** 順番を間違えた実装（悪い例）。& を最後に置くと二重エスケープになる */
function escapeHtmlWrongOrder(input: string): string {
  return input
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
    .replaceAll('&', '&amp;');
}

// ---------------------------------------------------------------------------
// 本文10節：CSP とセキュリティヘッダ（web の lib/security.ts と同じ実装）
// ---------------------------------------------------------------------------

const NONCE_BYTES = 16;

// web 側は Edge ランタイムで動くため Web Crypto を使うが、作る値の形は同じ
// （16バイトを16進数にした32文字）。src 側は node:crypto で同じものを作る。
function createNonce(): string {
  return randomBytes(NONCE_BYTES).toString('hex');
}

type CspOptions = { nonce: string; isDevelopment: boolean };

const REQUIRED_CSP_DIRECTIVES = [
  'default-src',
  'script-src',
  'style-src',
  'img-src',
  'object-src',
  'base-uri',
  'frame-ancestors',
] as const;

function buildCsp(options: CspOptions): string {
  const scriptSrc = options.isDevelopment
    ? `'self' 'nonce-${options.nonce}' 'strict-dynamic' 'unsafe-eval'`
    : `'self' 'nonce-${options.nonce}' 'strict-dynamic'`;

  return [
    `default-src 'self'`,
    `script-src ${scriptSrc}`,
    `style-src 'self' 'unsafe-inline'`,
    `img-src 'self' data:`,
    `font-src 'self'`,
    `connect-src 'self'`,
    `object-src 'none'`,
    `base-uri 'self'`,
    `form-action 'self'`,
    `frame-ancestors 'none'`,
  ].join('; ');
}

function cspHeaderName(reportOnly: boolean): string {
  return reportOnly ? 'Content-Security-Policy-Report-Only' : 'Content-Security-Policy';
}

function readCspDirective(csp: string, name: string): string | undefined {
  for (const part of csp.split(';')) {
    const trimmed = part.trim();

    if (trimmed === name) {
      return '';
    }

    if (trimmed.startsWith(`${name} `)) {
      return trimmed.slice(name.length + 1).trim();
    }
  }

  return undefined;
}

function missingCspDirectives(csp: string): string[] {
  return REQUIRED_CSP_DIRECTIVES.filter((name) => readCspDirective(csp, name) === undefined);
}

function scriptSrcAllowsUnsafeInline(csp: string): boolean {
  const value = readCspDirective(csp, 'script-src') ?? readCspDirective(csp, 'default-src') ?? '';

  return value.split(/\s+/).includes(`'unsafe-inline'`);
}

/** ディレクティブを1つ抜いた CSP を作る（検査が欠けを見つけられるか試すため） */
function removeCspDirective(csp: string, name: string): string {
  return csp
    .split(';')
    .map((part) => part.trim())
    .filter((part) => part !== name && !part.startsWith(`${name} `))
    .join('; ');
}

type HeaderMap = Record<string, string>;

type SecurityHeaderOptions = CspOptions & { reportOnly: boolean };

const REQUIRED_SECURITY_HEADERS = [
  'X-Content-Type-Options',
  'Referrer-Policy',
  'X-Frame-Options',
  'Strict-Transport-Security',
] as const;

function buildSecurityHeaders(options: SecurityHeaderOptions): HeaderMap {
  return {
    [cspHeaderName(options.reportOnly)]: buildCsp(options),
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'X-Frame-Options': 'DENY',
    'Strict-Transport-Security': 'max-age=63072000; includeSubDomains',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
  };
}

function missingSecurityHeaders(headers: HeaderMap): string[] {
  const missing: string[] = REQUIRED_SECURITY_HEADERS.filter(
    (name) => (headers[name] ?? '') === ''
  );

  const csp =
    headers['Content-Security-Policy'] ?? headers['Content-Security-Policy-Report-Only'] ?? '';

  if (csp === '') {
    missing.push('Content-Security-Policy');
  }

  return missing;
}

/** ヘッダを1つ抜いた一覧を作る（検査が欠けを見つけられるか試すため） */
function withoutHeader(headers: HeaderMap, name: string): HeaderMap {
  const copy: HeaderMap = { ...headers };

  delete copy[name];

  return copy;
}

// ---------------------------------------------------------------------------
// 本文9節：保護されたパスとレート制限の対象
// ---------------------------------------------------------------------------

const PROTECTED_PATH_PREFIXES = ['/orders', '/admin'] as const;

function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PATH_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );
}

type RateLimitRule = { limit: number; windowMs: number };

const API_RATE_LIMIT: RateLimitRule = { limit: 60, windowMs: 60_000 };
const AUTH_RATE_LIMIT: RateLimitRule = { limit: 20, windowMs: 60_000 };

function rateLimitRuleFor(pathname: string, method: string): RateLimitRule | null {
  if (pathname === '/api' || pathname.startsWith('/api/')) {
    return API_RATE_LIMIT;
  }

  if (method === 'POST' && (pathname === '/login' || pathname === '/signup')) {
    return AUTH_RATE_LIMIT;
  }

  return null;
}

/** 規則を短い文字列にして比べやすくする */
function describeRule(rule: RateLimitRule | null): string {
  return rule === null ? 'none' : `${String(rule.limit)}/${String(rule.windowMs)}`;
}

// ---------------------------------------------------------------------------
// 本文9節：レート制限の判定
// ---------------------------------------------------------------------------

type RateLimitState = { count: number; resetAt: number };

type RateLimitDecision =
  | { kind: 'allowed'; remaining: number }
  | { kind: 'blocked'; retryAfterSeconds: number };

function decideRateLimit(
  store: Map<string, RateLimitState>,
  key: string,
  now: number,
  rule: RateLimitRule
): RateLimitDecision {
  const current = store.get(key);

  if (current === undefined || current.resetAt <= now) {
    store.set(key, { count: 1, resetAt: now + rule.windowMs });

    return { kind: 'allowed', remaining: rule.limit - 1 };
  }

  if (current.count >= rule.limit) {
    return {
      kind: 'blocked',
      retryAfterSeconds: Math.max(1, Math.ceil((current.resetAt - now) / 1000)),
    };
  }

  store.set(key, { count: current.count + 1, resetAt: current.resetAt });

  return { kind: 'allowed', remaining: rule.limit - current.count - 1 };
}

function pruneRateLimitStore(store: Map<string, RateLimitState>, now: number): number {
  let removed = 0;

  for (const [key, state] of store) {
    if (state.resetAt <= now) {
      store.delete(key);
      removed += 1;
    }
  }

  return removed;
}

/** 判定結果を短い文字列にする */
function describeDecision(decision: RateLimitDecision): string {
  return decision.kind === 'allowed'
    ? `allowed:${String(decision.remaining)}`
    : `blocked:${String(decision.retryAfterSeconds)}`;
}

type HeaderReader = { get(name: string): string | null };

function clientKey(headers: HeaderReader, pathname: string): string {
  const forwarded = headers.get('x-forwarded-for') ?? '';
  const first = forwarded.split(',')[0]?.trim() ?? '';
  const address = first === '' ? 'unknown' : first;

  return `${address}|${pathname}`;
}

/** テスト用のヘッダ。Headers を作らずに get だけを持つ物を渡せる */
function fakeHeaders(values: Record<string, string>): HeaderReader {
  return { get: (name) => values[name.toLowerCase()] ?? null };
}

// ---------------------------------------------------------------------------
// 本文5節：CSRF（要求の出どころ）
// ---------------------------------------------------------------------------

function isTrustedOrigin(origin: string | null, host: string | null): boolean {
  if (origin === null || origin === '' || host === null || host === '') {
    return false;
  }

  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// 本文6節：認可漏れ（IDOR）
// ---------------------------------------------------------------------------

type OrderRow = { id: number; userId: number; status: string; totalAmount: number };

const ORDER_ROWS: OrderRow[] = [
  { id: 10, userId: 1, status: 'paid', totalAmount: 3080 },
  { id: 11, userId: 2, status: 'pending', totalAmount: 1980 },
  { id: 12, userId: 2, status: 'shipped', totalAmount: 5280 },
  { id: 13, userId: 3, status: 'cancelled', totalAmount: 2585 },
];

/** 一覧：ここは最初から絞れている（だから安全だと思い込んでしまう） */
function listOrdersForUser(rows: readonly OrderRow[], userId: number): OrderRow[] {
  return rows.filter((row) => row.userId === userId);
}

/** 詳細（悪い例）：URL の番号だけで引く。誰のものかを見ていない */
function findOrderByIdUnsafe(rows: readonly OrderRow[], orderId: number): OrderRow | undefined {
  return rows.find((row) => row.id === orderId);
}

/** 詳細（良い例）：「自分のものか」を問い合わせの条件に含める */
function findOrderForUser(
  rows: readonly OrderRow[],
  orderId: number,
  userId: number
): OrderRow | undefined {
  return rows.find((row) => row.id === orderId && row.userId === userId);
}

/** すべての利用者×すべての注文を試し、他人の注文が取れた回数を数える */
function countLeaks(
  fetchOrder: (orderId: number, userId: number) => OrderRow | undefined
): number {
  let leaks = 0;

  for (const userId of [1, 2, 3]) {
    for (const row of ORDER_ROWS) {
      const found = fetchOrder(row.id, userId);

      if (found !== undefined && found.userId !== userId) {
        leaks += 1;
      }
    }
  }

  return leaks;
}

// ---------------------------------------------------------------------------
// 本文7節：環境変数の検証（web の lib/env.ts と同じ実装）
// ---------------------------------------------------------------------------

const envSchema = z.object({
  DATABASE_URL: z
    .string({ error: 'DATABASE_URL を設定してください' })
    .min(1, { error: 'DATABASE_URL を設定してください' })
    .refine((value) => value.startsWith('postgresql://'), {
      error: 'DATABASE_URL は postgresql:// で始まる接続文字列にしてください',
    }),
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
});

type AppEnv = z.infer<typeof envSchema>;

type EnvCheck =
  | { kind: 'ok'; env: AppEnv }
  | { kind: 'invalid'; missing: string[]; invalid: string[] };

function uniqueNames(names: string[]): string[] {
  return [...new Set(names)].sort();
}

function parseEnv(source: Record<string, string | undefined>): EnvCheck {
  const result = envSchema.safeParse({
    DATABASE_URL: source['DATABASE_URL'],
    NODE_ENV: source['NODE_ENV'],
  });

  if (result.success) {
    return { kind: 'ok', env: result.data };
  }

  const missing: string[] = [];
  const invalid: string[] = [];

  for (const issue of result.error.issues) {
    const name = issue.path.map((segment) => String(segment)).join('.');

    if (issue.code === 'invalid_type') {
      missing.push(name);
    } else {
      invalid.push(name);
    }
  }

  return { kind: 'invalid', missing: uniqueNames(missing), invalid: uniqueNames(invalid) };
}

function describeEnvFailure(check: Extract<EnvCheck, { kind: 'invalid' }>): string {
  const missing = check.missing.length === 0 ? 'なし' : check.missing.join(', ');
  const invalid = check.invalid.length === 0 ? 'なし' : check.invalid.join(', ');

  return `環境変数の設定に問題があります（不足: ${missing} / 形式が不正: ${invalid}）`;
}

/** 失敗した変数の名前をまとめて並べる（不足・不正の内訳に依存しない比べ方） */
function failedEnvNames(check: EnvCheck): string[] {
  return check.kind === 'ok' ? [] : uniqueNames([...check.missing, ...check.invalid]);
}

const PUBLIC_ENV_PREFIX = 'NEXT_PUBLIC_';

const SECRET_NAME_PARTS = ['SECRET', 'TOKEN', 'PASSWORD', 'PRIVATE', 'KEY', 'CREDENTIAL'] as const;

function findLeakedPublicSecrets(source: Record<string, string | undefined>): string[] {
  return Object.keys(source)
    .filter((name) => name.startsWith(PUBLIC_ENV_PREFIX))
    .filter((name) => {
      const upper = name.toUpperCase();

      return SECRET_NAME_PARTS.some((part) => upper.includes(part));
    })
    .sort();
}

// ---------------------------------------------------------------------------
// 本文8節：ログのマスク（web の lib/security.ts と同じ実装）
// ---------------------------------------------------------------------------

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
  const lower = key.toLowerCase();

  return SENSITIVE_KEY_PARTS.some((part) => lower.includes(part));
}

function maskSensitive(input: Record<string, unknown>): Record<string, unknown> {
  const masked: Record<string, unknown> = {};

  for (const [key, value] of Object.entries(input)) {
    masked[key] = isSensitiveKey(key) ? REDACTED : value;
  }

  return masked;
}

function maskCardNumber(raw: string): string {
  const digits = raw.replace(/\D/g, '');

  if (digits.length <= 4) {
    return '*'.repeat(digits.length);
  }

  return `${'*'.repeat(digits.length - 4)}${digits.slice(-4)}`;
}

function maskEmail(raw: string): string {
  const separator = raw.lastIndexOf('@');

  if (separator <= 0) {
    return REDACTED;
  }

  return `${raw.slice(0, 1)}***@${raw.slice(separator + 1)}`;
}

function maskTextSecrets(text: string): string {
  return text
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/g, `Bearer ${REDACTED}`)
    .replace(/\b\d{13,19}\b/g, (digits) => maskCardNumber(digits));
}

// ---------------------------------------------------------------------------
// 検証本体
// ---------------------------------------------------------------------------
function main(): void {
  // --- 3節：HTML エスケープ ----------------------------------------------
  checkString('本文3節: タグの記号がエスケープされる', escapeHtml('<b>石けん</b>'), '&lt;b&gt;石けん&lt;/b&gt;');
  checkString('本文3節: & がエスケープされる', escapeHtml('お茶 & コーヒー'), 'お茶 &amp; コーヒー');
  checkString('本文3節: 二重引用符', escapeHtml('"引用"'), '&quot;引用&quot;');
  checkString('本文3節: 単一引用符', escapeHtml("it's"), 'it&#39;s');
  checkString('本文3節: 普通の日本語は何も変わらない', escapeHtml('マグカップ 2350円'), 'マグカップ 2350円');
  checkString('本文3節: 空文字も例外にならない', escapeHtml(''), '');

  // & を最初に処理しているので、自分が作った実体参照を壊さない
  checkString('本文3節: 二重エスケープしない', escapeHtml('<'), '&lt;');
  checkString('本文3節: 順番を間違えると二重エスケープになる', escapeHtmlWrongOrder('<'), '&amp;lt;');
  checkBoolean(
    '本文3節: 2回かけると結果が変わる（だから1回だけ通す）',
    escapeHtml(escapeHtml('お茶 & コーヒー')) === escapeHtml('お茶 & コーヒー'),
    false
  );

  // --- 10節：nonce -------------------------------------------------------
  const nonce = createNonce();

  checkNumber('本文10節: nonce は32文字（16バイトの16進数）', nonce.length, 32);
  checkBoolean('本文10節: 16進数の文字だけ', /^[0-9a-f]{32}$/.test(nonce), true);
  checkBoolean('本文10節: 毎回違う値になる', createNonce() === createNonce(), false);

  const nonces = new Set<string>();

  for (let index = 0; index < 200; index += 1) {
    nonces.add(createNonce());
  }

  checkNumber('本文10節: 200回作って重複なし', nonces.size, 200);

  // --- 10節：CSP ---------------------------------------------------------
  const csp = buildCsp({ nonce, isDevelopment: false });

  checkJson('本文10節: 必須のディレクティブがすべて入っている', missingCspDirectives(csp), []);
  checkString('本文10節: object-src は none', readCspDirective(csp, 'object-src') ?? '', `'none'`);
  checkString('本文10節: base-uri は self', readCspDirective(csp, 'base-uri') ?? '', `'self'`);
  checkString(
    '本文10節: frame-ancestors は none（iframe に入れさせない）',
    readCspDirective(csp, 'frame-ancestors') ?? '',
    `'none'`
  );
  checkString(
    '本文10節: script-src に nonce が入っている',
    readCspDirective(csp, 'script-src') ?? '',
    `'self' 'nonce-${nonce}' 'strict-dynamic'`
  );
  checkBoolean('本文10節: script-src に unsafe-inline を入れていない', scriptSrcAllowsUnsafeInline(csp), false);
  checkBoolean(
    '本文10節: 開発時だけ unsafe-eval が付く',
    buildCsp({ nonce, isDevelopment: true }).includes(`'unsafe-eval'`),
    true
  );
  checkBoolean(
    '本文10節: 本番では unsafe-eval を付けない',
    csp.includes(`'unsafe-eval'`),
    false
  );

  // unsafe-inline を入れてしまった CSP を検出できること
  checkBoolean(
    '本文10節: unsafe-inline の混入を検出できる',
    scriptSrcAllowsUnsafeInline(`default-src 'self'; script-src 'self' 'unsafe-inline'`),
    true
  );

  // ディレクティブが1つ欠けたら検出できること（欠けを見逃す検査は役に立たない）
  for (const name of REQUIRED_CSP_DIRECTIVES) {
    checkJson(
      `本文10節: ${name} の欠けを検出できる`,
      missingCspDirectives(removeCspDirective(csp, name)),
      [name]
    );
  }

  // --- 10節：セキュリティヘッダ ------------------------------------------
  const headers = buildSecurityHeaders({ nonce, isDevelopment: false, reportOnly: false });

  checkJson('本文10節: 必須のヘッダがすべて付いている', missingSecurityHeaders(headers), []);
  checkString('本文10節: 型の推測を止める', headers['X-Content-Type-Options'] ?? '', 'nosniff');
  checkString(
    '本文10節: リファラの送り方',
    headers['Referrer-Policy'] ?? '',
    'strict-origin-when-cross-origin'
  );
  checkString('本文10節: 古いブラウザ向けの iframe 禁止', headers['X-Frame-Options'] ?? '', 'DENY');
  checkBoolean(
    '本文10節: HSTS に max-age がある',
    (headers['Strict-Transport-Security'] ?? '').includes('max-age='),
    true
  );

  for (const name of [...REQUIRED_SECURITY_HEADERS, 'Content-Security-Policy']) {
    checkJson(`本文10節: ${name} の欠けを検出できる`, missingSecurityHeaders(withoutHeader(headers, name)), [
      name,
    ]);
  }

  // 段階導入（報告だけ）にしてもヘッダの検査は通る
  const reportOnlyHeaders = buildSecurityHeaders({ nonce, isDevelopment: false, reportOnly: true });

  checkJson('本文10節: 報告だけの設定でも欠けは無い', missingSecurityHeaders(reportOnlyHeaders), []);
  checkBoolean(
    '本文10節: 報告だけのときはヘッダ名が変わる',
    Object.keys(reportOnlyHeaders).includes('Content-Security-Policy-Report-Only'),
    true
  );
  checkString('本文10節: ヘッダ名の切り替え（適用）', cspHeaderName(false), 'Content-Security-Policy');
  checkString(
    '本文10節: ヘッダ名の切り替え（報告のみ）',
    cspHeaderName(true),
    'Content-Security-Policy-Report-Only'
  );

  // --- 9節：保護されたパスの判定 ------------------------------------------
  checkBoolean('本文9節: /orders は保護対象', isProtectedPath('/orders'), true);
  checkBoolean('本文9節: /orders/12 も保護対象', isProtectedPath('/orders/12'), true);
  checkBoolean('本文9節: /admin は保護対象', isProtectedPath('/admin'), true);
  checkBoolean('本文9節: /admin/products も保護対象', isProtectedPath('/admin/products'), true);
  checkBoolean('本文9節: トップページは保護対象でない', isProtectedPath('/'), false);
  checkBoolean('本文9節: /products は保護対象でない', isProtectedPath('/products'), false);
  checkBoolean('本文9節: /orders-archive を巻き込まない', isProtectedPath('/orders-archive'), false);
  checkBoolean('本文9節: /login は保護対象でない（無限に転送される）', isProtectedPath('/login'), false);

  // --- 9節：レート制限の対象 ---------------------------------------------
  checkString('本文9節: API は制限の対象', describeRule(rateLimitRuleFor('/api/products', 'GET')), '60/60000');
  checkString('本文9節: /api 直下も対象', describeRule(rateLimitRuleFor('/api', 'GET')), '60/60000');
  checkString('本文9節: ログインの送信は厳しめ', describeRule(rateLimitRuleFor('/login', 'POST')), '20/60000');
  checkString('本文9節: 新規登録の送信も対象', describeRule(rateLimitRuleFor('/signup', 'POST')), '20/60000');
  checkString('本文9節: ログイン画面の表示は対象外', describeRule(rateLimitRuleFor('/login', 'GET')), 'none');
  checkString('本文9節: 商品一覧の表示は対象外', describeRule(rateLimitRuleFor('/products', 'GET')), 'none');

  // --- 9節：レート制限の判定 ---------------------------------------------
  const store = new Map<string, RateLimitState>();
  const rule: RateLimitRule = { limit: 5, windowMs: 60_000 };
  const base = 1_800_000_000_000;
  const key = '203.0.113.10|/api/products';

  checkString('本文9節: 1回目は通る', describeDecision(decideRateLimit(store, key, base, rule)), 'allowed:4');
  checkString('本文9節: 2回目は通る', describeDecision(decideRateLimit(store, key, base, rule)), 'allowed:3');
  checkString('本文9節: 3回目は通る', describeDecision(decideRateLimit(store, key, base, rule)), 'allowed:2');
  checkString('本文9節: 4回目は通る', describeDecision(decideRateLimit(store, key, base, rule)), 'allowed:1');
  checkString('本文9節: 5回目でちょうど上限', describeDecision(decideRateLimit(store, key, base, rule)), 'allowed:0');
  checkString(
    '本文9節: 6回目は弾かれる（Retry-After は60秒）',
    describeDecision(decideRateLimit(store, key, base, rule)),
    'blocked:60'
  );
  checkString(
    '本文9節: 30秒後に試すと残り30秒と言われる',
    describeDecision(decideRateLimit(store, key, base + 30_000, rule)),
    'blocked:30'
  );

  // 相手が違えば別に数える（1人の使いすぎで全員が止まらない）
  checkString(
    '本文9節: 別の相手は影響を受けない',
    describeDecision(decideRateLimit(store, '198.51.100.7|/api/products', base, rule)),
    'allowed:4'
  );

  // 時間窓が過ぎたら回復する
  checkString(
    '本文9節: 時間窓が過ぎたら数え直す',
    describeDecision(decideRateLimit(store, key, base + 60_000, rule)),
    'allowed:4'
  );

  checkNumber('本文9節: 記録の件数', store.size, 2);
  checkNumber('本文9節: 期限切れの記録を捨てる', pruneRateLimitStore(store, base + 200_000), 2);
  checkNumber('本文9節: 掃除のあとは空になる', store.size, 0);

  // 同じ相手でもパスが違えば別の枠（キーの作り方）
  const withIp = fakeHeaders({ 'x-forwarded-for': '203.0.113.10, 70.41.3.18' });

  checkString('本文9節: 先頭のアドレスを使う', clientKey(withIp, '/api/products'), '203.0.113.10|/api/products');
  checkString(
    '本文9節: パスごとに別の枠になる',
    clientKey(withIp, '/api/orders/10'),
    '203.0.113.10|/api/orders/10'
  );
  checkString(
    '本文9節: ヘッダが無い場合（開発環境）',
    clientKey(fakeHeaders({}), '/api/products'),
    'unknown|/api/products'
  );

  // --- 5節：CSRF（要求の出どころ） ----------------------------------------
  checkBoolean(
    '本文5節: 自分のサイトからの送信は通す',
    isTrustedOrigin('http://localhost:3000', 'localhost:3000'),
    true
  );
  checkBoolean(
    '本文5節: 別のサイトからの送信は通さない',
    isTrustedOrigin('https://another.example', 'localhost:3000'),
    false
  );
  checkBoolean('本文5節: Origin が無い要求は通さない', isTrustedOrigin(null, 'localhost:3000'), false);
  checkBoolean('本文5節: Host が無い要求は通さない', isTrustedOrigin('http://localhost:3000', null), false);
  checkBoolean(
    '本文5節: URL として読めない値は通さない',
    isTrustedOrigin('localhost:3000', 'localhost:3000'),
    false
  );
  checkBoolean(
    '本文5節: ポートが違えば別のサイト',
    isTrustedOrigin('http://localhost:3001', 'localhost:3000'),
    false
  );

  // --- 6節：認可漏れ（IDOR） ---------------------------------------------
  checkJson(
    '本文6節: 一覧は自分の注文だけ（ここは最初から正しい）',
    listOrdersForUser(ORDER_ROWS, 1).map((row) => row.id),
    [10]
  );
  checkJson(
    '本文6節: 利用者2の一覧',
    listOrdersForUser(ORDER_ROWS, 2).map((row) => row.id),
    [11, 12]
  );

  // 詳細を id だけで引くと、一覧に出ていない注文まで取れてしまう
  checkNumber(
    '本文6節: id だけで引くと他人の注文が取れる',
    countLeaks((orderId) => findOrderByIdUnsafe(ORDER_ROWS, orderId)),
    8
  );
  checkNumber(
    '本文6節: 条件に userId を入れれば1件も漏れない',
    countLeaks((orderId, userId) => findOrderForUser(ORDER_ROWS, orderId, userId)),
    0
  );

  checkBoolean(
    '本文6節: 自分の注文は取れる',
    findOrderForUser(ORDER_ROWS, 10, 1) !== undefined,
    true
  );
  checkBoolean(
    '本文6節: 他人の注文は取れない',
    findOrderForUser(ORDER_ROWS, 11, 1) === undefined,
    true
  );
  checkBoolean(
    '本文6節: 存在しない注文も取れない（区別しないので同じ結果）',
    findOrderForUser(ORDER_ROWS, 999, 1) === undefined,
    true
  );

  // --- 7節：環境変数の検証 ------------------------------------------------
  const validSource = {
    DATABASE_URL: 'postgresql://shop:shop_password@db:5432/shop',
    NODE_ENV: 'production',
  };
  const okCheck = parseEnv(validSource);

  checkString('本文7節: 揃っていれば ok', okCheck.kind, 'ok');
  checkString(
    '本文7節: NODE_ENV が読める',
    okCheck.kind === 'ok' ? okCheck.env.NODE_ENV : '',
    'production'
  );
  checkString(
    '本文7節: 指定が無ければ development',
    (() => {
      const check = parseEnv({ DATABASE_URL: validSource.DATABASE_URL });

      return check.kind === 'ok' ? check.env.NODE_ENV : '';
    })(),
    'development'
  );

  const missingCheck = parseEnv({});

  checkJson('本文7節: 設定が無ければ失敗する', failedEnvNames(missingCheck), ['DATABASE_URL']);
  checkBoolean(
    '本文7節: 未設定は「不足」に分類される',
    missingCheck.kind === 'invalid' && missingCheck.missing.includes('DATABASE_URL'),
    true
  );

  const emptyCheck = parseEnv({ DATABASE_URL: '' });

  checkJson('本文7節: 空文字も失敗する', failedEnvNames(emptyCheck), ['DATABASE_URL']);
  checkBoolean(
    '本文7節: 空文字は「形式が不正」に分類される',
    emptyCheck.kind === 'invalid' && emptyCheck.invalid.includes('DATABASE_URL'),
    true
  );

  const wrongCheck = parseEnv({ DATABASE_URL: 'mysql://shop:shop_password@db:3306/shop' });

  checkJson('本文7節: 別のデータベースの接続文字列も弾く', failedEnvNames(wrongCheck), ['DATABASE_URL']);
  checkJson(
    '本文7節: 知らない NODE_ENV も弾く',
    failedEnvNames(parseEnv({ DATABASE_URL: validSource.DATABASE_URL, NODE_ENV: 'staging' })),
    ['NODE_ENV']
  );

  // ここが要点。失敗のメッセージに値（パスワードを含む接続文字列）を混ぜない
  const failureMessage = wrongCheck.kind === 'invalid' ? describeEnvFailure(wrongCheck) : '';

  checkBoolean('本文7節: メッセージに変数の名前は出る', failureMessage.includes('DATABASE_URL'), true);
  checkBoolean(
    '本文7節: メッセージにパスワードを出さない',
    failureMessage.includes('shop_password'),
    false
  );
  checkBoolean('本文7節: メッセージに値そのものを出さない', failureMessage.includes('mysql://'), false);

  // NEXT_PUBLIC_ が付いた秘密らしい名前を見つける
  checkJson(
    '本文7節: ブラウザに埋まる秘密を見つける',
    findLeakedPublicSecrets({
      DATABASE_URL: validSource.DATABASE_URL,
      PAYMENT_WEBHOOK_SECRET: 'local-secret',
      NEXT_PUBLIC_SITE_NAME: 'ミニ雑貨ショップ',
      NEXT_PUBLIC_API_KEY: 'should-not-be-here',
    }),
    ['NEXT_PUBLIC_API_KEY']
  );
  checkJson(
    '本文7節: 公開してよい名前は挙げない',
    findLeakedPublicSecrets({ NEXT_PUBLIC_SITE_NAME: 'ミニ雑貨ショップ' }),
    []
  );

  // --- 8節：ログのマスク --------------------------------------------------
  checkBoolean('本文8節: password は伏せる', isSensitiveKey('password'), true);
  checkBoolean('本文8節: passwordHash も伏せる', isSensitiveKey('passwordHash'), true);
  checkBoolean('本文8節: sessionId も伏せる', isSensitiveKey('sessionId'), true);
  checkBoolean('本文8節: Authorization も伏せる（大文字でも）', isSensitiveKey('Authorization'), true);
  checkBoolean('本文8節: cardNumber も伏せる', isSensitiveKey('cardNumber'), true);
  checkBoolean('本文8節: quantity は伏せない', isSensitiveKey('quantity'), false);
  checkBoolean('本文8節: productId は伏せない', isSensitiveKey('productId'), false);

  const logged = maskSensitive({
    productId: 3,
    quantity: 2,
    password: 'lavender-2026',
    sessionId: 'a1b2c3',
    cardNumber: '4242424242424242',
  });

  checkJson('本文8節: 伏せるものと残すものを分ける', logged, {
    productId: 3,
    quantity: 2,
    password: REDACTED,
    sessionId: REDACTED,
    cardNumber: REDACTED,
  });
  checkBoolean(
    '本文8節: マスク後の JSON に元の値が残っていない',
    JSON.stringify(logged).includes('lavender-2026'),
    false
  );

  checkString('本文8節: カード番号は下4桁だけ', maskCardNumber('4242424242424242'), '************4242');
  checkString('本文8節: 区切りがあっても同じ', maskCardNumber('4242 4242 4242 4242'), '************4242');
  checkString('本文8節: 短すぎる値は全部伏せる', maskCardNumber('123'), '***');
  checkString('本文8節: メールアドレスは先頭1文字とドメイン', maskEmail('demo@example.com'), 'd***@example.com');
  checkString('本文8節: @ が無い値は全部伏せる', maskEmail('not-an-address'), REDACTED);
  checkString('本文8節: 先頭が @ の値も全部伏せる', maskEmail('@example.com'), REDACTED);

  const rawLog = '決済に失敗: Bearer sk_live_abc.def-123 / カード 4242424242424242 を使用';
  const safeLog = maskTextSecrets(rawLog);

  checkString(
    '本文8節: 文章に混ざった秘密も伏せる',
    safeLog,
    `決済に失敗: Bearer ${REDACTED} / カード ************4242 を使用`
  );
  checkBoolean('本文8節: トークンが残っていない', safeLog.includes('sk_live_abc'), false);
  checkBoolean('本文8節: カード番号が残っていない', safeLog.includes('4242424242424242'), false);
  checkString('本文8節: 秘密が無い文章は変えない', maskTextSecrets('注文 #10 を確定しました'), '注文 #10 を確定しました');

  // ---------------------------------------------------------------------------
  // 結果
  // ---------------------------------------------------------------------------
  if (failedCount > 0) {
    console.error(`session26: ${failedCount} 件の検証に失敗しました`);
    process.exit(1);
  }

  console.log('session26: ok');
}

main();
