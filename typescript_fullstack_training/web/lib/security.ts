// 防御のための純粋な関数だけを集めたモジュール（セッション26）。
//
// ここには Prisma も React も node:crypto も import しない。理由は2つある。
//   1. middleware.ts から使うので、Edge ランタイムで動く必要がある
//      （node:crypto や PrismaClient は使えない。乱数は Web Crypto の
//       crypto.getRandomValues を使う）
//   2. 引数だけで結果が決まる関数にしておくと、同じ実装を
//      src/session26/verify.ts で検証できる
//
// セキュリティのコードは「動いた」では正しさが分からない。だから
// 「判定」と「適用」を分け、判定側をここに集めて検証可能にしている。

// ---------------------------------------------------------------------------
// 1. HTML エスケープ
// ---------------------------------------------------------------------------

/**
 * HTML で特別な意味を持つ5文字を実体参照に置き換える。
 *
 * 置き換える順番が重要で、& を最初に処理する。最後に回すと、自分が
 * 作った &lt; の & まで置き換えて &amp;lt; になってしまう（二重エスケープ）。
 *
 * React の JSX に {値} と書く場合、この処理は React が自動で行うので
 * 呼ぶ必要はない。使うのは「HTML の文字列を自分で組み立てるとき」だけ。
 */
export function escapeHtml(input: string): string {
  return input
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

// ---------------------------------------------------------------------------
// 2. Content Security Policy（CSP）
// ---------------------------------------------------------------------------

/** nonce のバイト数。16バイト＝128ビットあれば推測できない */
const NONCE_BYTES = 16;

/**
 * 要求1件ごとに使い捨てる nonce（number used once）を作る。
 * Edge ランタイムでも使える Web Crypto を使う（node:crypto は使えない）。
 */
export function createNonce(): string {
  const bytes = new Uint8Array(NONCE_BYTES);

  crypto.getRandomValues(bytes);

  let hex = '';

  for (const byte of bytes) {
    hex += byte.toString(16).padStart(2, '0');
  }

  return hex;
}

export type CspOptions = {
  /** この要求のために作った使い捨ての値 */
  nonce: string;
  /** 開発サーバー（next dev）では追加の許可が必要になる */
  isDevelopment: boolean;
};

/** CSP に必ず入れるディレクティブ。1つでも欠けたら穴になる */
export const REQUIRED_CSP_DIRECTIVES = [
  'default-src',
  'script-src',
  'style-src',
  'img-src',
  'object-src',
  'base-uri',
  'frame-ancestors',
] as const;

/**
 * CSP のヘッダ値を組み立てる。
 *
 * script-src に 'unsafe-inline' を入れないことが最大のポイント。入れた瞬間、
 * ページに挿し込まれた <script> が実行できるようになり、CSP の意味がほぼ消える。
 * 代わりに nonce を使い、自分が出したスクリプトだけを許可する。
 */
export function buildCsp(options: CspOptions): string {
  // 開発サーバーは変更を反映するために eval を使うので、開発時だけ許可する
  const scriptSrc = options.isDevelopment
    ? `'self' 'nonce-${options.nonce}' 'strict-dynamic' 'unsafe-eval'`
    : `'self' 'nonce-${options.nonce}' 'strict-dynamic'`;

  const directives = [
    // 既定の行き先は自分のサイトだけ
    `default-src 'self'`,
    `script-src ${scriptSrc}`,
    // style だけは 'unsafe-inline' を許している（後述の割り切り）
    `style-src 'self' 'unsafe-inline'`,
    `img-src 'self' data:`,
    `font-src 'self'`,
    `connect-src 'self'`,
    // <object> <embed> は使わないので全面禁止
    `object-src 'none'`,
    // <base> タグで相対URLの起点をすり替えられないようにする
    `base-uri 'self'`,
    // フォームの送信先を自分のサイトに限る
    `form-action 'self'`,
    // 他サイトの iframe に入れさせない（X-Frame-Options の後継）
    `frame-ancestors 'none'`,
  ];

  return directives.join('; ');
}

/** 段階導入用。報告だけさせたいときはヘッダ名を変える（挙動は変えない） */
export function cspHeaderName(reportOnly: boolean): string {
  return reportOnly ? 'Content-Security-Policy-Report-Only' : 'Content-Security-Policy';
}

/** CSP の文字列から、指定したディレクティブの値を取り出す（無ければ undefined） */
export function readCspDirective(csp: string, name: string): string | undefined {
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

/** 必須のディレクティブのうち、欠けているものを挙げる */
export function missingCspDirectives(csp: string): string[] {
  return REQUIRED_CSP_DIRECTIVES.filter((name) => readCspDirective(csp, name) === undefined);
}

/**
 * script-src が 'unsafe-inline' を許してしまっていないか。
 * script-src が無い場合は default-src が使われるので、そちらを見る。
 */
export function scriptSrcAllowsUnsafeInline(csp: string): boolean {
  const value = readCspDirective(csp, 'script-src') ?? readCspDirective(csp, 'default-src') ?? '';

  return value.split(/\s+/).includes(`'unsafe-inline'`);
}

// ---------------------------------------------------------------------------
// 3. セキュリティヘッダ
// ---------------------------------------------------------------------------

/** ヘッダ名から値を引く形。middleware ではこれをそのまま response に写す */
export type HeaderMap = Record<string, string>;

export type SecurityHeaderOptions = CspOptions & {
  /** true なら CSP を「報告だけ」にする（段階導入の1歩目） */
  reportOnly: boolean;
};

/** CSP 以外に必ず付けるヘッダ。1つでも欠けたら検出できるように名前を並べておく */
export const REQUIRED_SECURITY_HEADERS = [
  'X-Content-Type-Options',
  'Referrer-Policy',
  'X-Frame-Options',
  'Strict-Transport-Security',
] as const;

/** すべての応答に付けるヘッダの一覧を作る */
export function buildSecurityHeaders(options: SecurityHeaderOptions): HeaderMap {
  return {
    [cspHeaderName(options.reportOnly)]: buildCsp(options),
    // 拡張子や中身から型を推測させない（.txt を script として実行されるのを防ぐ）
    'X-Content-Type-Options': 'nosniff',
    // 他サイトへ移動するとき、URL のパスやクエリを送らない
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    // 古いブラウザ向けの frame-ancestors 相当
    'X-Frame-Options': 'DENY',
    // 以後このドメインには必ず HTTPS で来させる（http では無視される）
    'Strict-Transport-Security': 'max-age=63072000; includeSubDomains',
    // 使わない機能は最初から閉じる
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
  };
}

/** 必須のヘッダのうち、欠けている（または値が空の）ものを挙げる */
export function missingSecurityHeaders(headers: HeaderMap): string[] {
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

// ---------------------------------------------------------------------------
// 4. 保護されたパスとレート制限の対象
// ---------------------------------------------------------------------------

/**
 * ログインが必要なページ。middleware の matcher を広げたので自分で判定する。
 * 最終プロジェクトで /cart と /checkout を追加した（カートも注文も
 * 「誰のものか」で内容が変わるページなので、未ログインでは意味がない）。
 */
export const PROTECTED_PATH_PREFIXES = ['/orders', '/admin', '/cart', '/checkout'] as const;

/** そのパスはログインが必要か。/orders-archive のような別のパスを巻き込まないこと */
export function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PATH_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );
}

export type RateLimitRule = {
  /** 時間窓のあいだに許す回数 */
  limit: number;
  /** 時間窓の長さ（ミリ秒） */
  windowMs: number;
};

/** JSON を返す口。機械から呼ばれるので回数を絞る */
export const API_RATE_LIMIT: RateLimitRule = { limit: 60, windowMs: 60_000 };

/** ログイン・新規登録の送信。総当たりを現実的でない速さにする */
export const AUTH_RATE_LIMIT: RateLimitRule = { limit: 20, windowMs: 60_000 };

/** そのパスと方法に適用する制限。対象外なら null */
export function rateLimitRuleFor(pathname: string, method: string): RateLimitRule | null {
  if (pathname === '/api' || pathname.startsWith('/api/')) {
    return API_RATE_LIMIT;
  }

  if (method === 'POST' && (pathname === '/login' || pathname === '/signup')) {
    return AUTH_RATE_LIMIT;
  }

  return null;
}

// ---------------------------------------------------------------------------
// 5. レート制限の判定
// ---------------------------------------------------------------------------

export type RateLimitState = {
  count: number;
  /** この時刻を過ぎたら数え直す（エポックミリ秒） */
  resetAt: number;
};

export type RateLimitDecision =
  | { kind: 'allowed'; remaining: number }
  | { kind: 'blocked'; retryAfterSeconds: number };

/**
 * 数を数えて通すかどうかを決める。時刻を引数で受け取るので、
 * テストでは実時間を待たずに時間窓の経過を再現できる。
 */
export function decideRateLimit(
  store: Map<string, RateLimitState>,
  key: string,
  now: number,
  rule: RateLimitRule
): RateLimitDecision {
  const current = store.get(key);

  // 初回、または時間窓が過ぎている＝1から数え直す
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

/** 期限切れの記録を捨てる。これをしないと Map が無限に伸びる */
export function pruneRateLimitStore(store: Map<string, RateLimitState>, now: number): number {
  let removed = 0;

  for (const [key, state] of store) {
    if (state.resetAt <= now) {
      store.delete(key);
      removed += 1;
    }
  }

  return removed;
}

// 記録の置き場所はサーバーのメモリ。サーバーが2台になれば台ごとに数えるので
// 実際の上限は2倍になる（本文の第9節）。実務では Redis のような共有の記憶に置く。
const rateLimitStore = new Map<string, RateLimitState>();

/** 掃除の起動しきい値。要求ごとに全件走査しないための工夫 */
const PRUNE_THRESHOLD = 1000;

/** middleware から呼ぶ入口。判定そのものは decideRateLimit に任せる */
export function checkRateLimit(key: string, now: number, rule: RateLimitRule): RateLimitDecision {
  if (rateLimitStore.size > PRUNE_THRESHOLD) {
    pruneRateLimitStore(rateLimitStore, now);
  }

  return decideRateLimit(rateLimitStore, key, now, rule);
}

/** ヘッダを読めるものだけを要求する型（Headers でもテスト用の偽物でも渡せる） */
export type HeaderReader = { get(name: string): string | null };

/**
 * 「同じ相手」を表すキーを作る。X-Forwarded-For は書き換えられるので、
 * これは正確な身元ではなく「同じ相手らしさ」の目印にすぎない。
 */
export function clientKey(headers: HeaderReader, pathname: string): string {
  const forwarded = headers.get('x-forwarded-for') ?? '';
  const first = forwarded.split(',')[0]?.trim() ?? '';
  const address = first === '' ? 'unknown' : first;

  return `${address}|${pathname}`;
}

// ---------------------------------------------------------------------------
// 6. CSRF：要求の出どころを確かめる
// ---------------------------------------------------------------------------

/**
 * Origin ヘッダが自分のサイトを指しているか。
 * Server Actions は Next.js がこれと同じ確認を自動で行う。自分でルート
 * ハンドラを書いて状態を変える場合は、自分で確かめる必要がある。
 */
export function isTrustedOrigin(origin: string | null, host: string | null): boolean {
  if (origin === null || origin === '' || host === null || host === '') {
    return false;
  }

  try {
    return new URL(origin).host === host;
  } catch {
    // URL として解釈できない値は信頼しない
    return false;
  }
}

// ---------------------------------------------------------------------------
// 7. ログに出してはいけないものを伏せる
// ---------------------------------------------------------------------------

/** 伏せた値の表し方。伏せたこと自体は分かるようにする */
export const REDACTED = '[REDACTED]';

/** 名前にこれらを含むキーの値は、そのままログに出さない */
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

export function isSensitiveKey(key: string): boolean {
  const lower = key.toLowerCase();

  return SENSITIVE_KEY_PARTS.some((part) => lower.includes(part));
}

/** ログに出してよい形のオブジェクトを作る（1階層だけ。セッション18の拡張） */
export function maskSensitive(input: Record<string, unknown>): Record<string, unknown> {
  const masked: Record<string, unknown> = {};

  for (const [key, value] of Object.entries(input)) {
    masked[key] = isSensitiveKey(key) ? REDACTED : value;
  }

  return masked;
}

/** カード番号は下4桁だけ残す（下4桁は本人確認のために残してよい範囲） */
export function maskCardNumber(raw: string): string {
  const digits = raw.replace(/\D/g, '');

  if (digits.length <= 4) {
    return '*'.repeat(digits.length);
  }

  return `${'*'.repeat(digits.length - 4)}${digits.slice(-4)}`;
}

/** メールアドレスは先頭1文字とドメインだけ残す */
export function maskEmail(raw: string): string {
  const separator = raw.lastIndexOf('@');

  if (separator <= 0) {
    return REDACTED;
  }

  const local = raw.slice(0, separator);
  const domain = raw.slice(separator + 1);

  return `${local.slice(0, 1)}***@${domain}`;
}

/**
 * 文章の中に混ざった秘密を伏せる。
 * 例外のメッセージや外部サービスの応答をそのままログに書くと、
 * キーの名前が付いていない秘密が紛れ込む。
 */
export function maskTextSecrets(text: string): string {
  return text
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/g, `Bearer ${REDACTED}`)
    .replace(/\b\d{13,19}\b/g, (digits) => maskCardNumber(digits));
}
