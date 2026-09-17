// 復習04 の道具箱。
//
// セッション26「Webアプリケーションのセキュリティ」と セッション27「キャッシュ・
// パフォーマンス・ロギング」で web/lib に書いた関数の写し。
// src からは web を import できないため、仕様を変えずに複製している。
// この章の問題では、これらを「すでに手元にある道具」として組み合わせて使う。

// ---------------------------------------------------------------------------
// セッション26：ログのマスク（web の lib/security.ts と同じ実装）
// ---------------------------------------------------------------------------

export const REDACTED = '[REDACTED]';

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

/** カード番号は下4桁だけ残す */
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

  return `${raw.slice(0, 1)}***@${raw.slice(separator + 1)}`;
}

/** 文章の中に紛れた秘密（Bearer トークン・長い数字の並び）を伏せる */
export function maskTextSecrets(text: string): string {
  return text
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/g, `Bearer ${REDACTED}`)
    .replace(/\b\d{13,19}\b/g, (digits) => maskCardNumber(digits));
}

// ---------------------------------------------------------------------------
// セッション26：要求の出どころ（CSRF）とレート制限
// ---------------------------------------------------------------------------

export function isTrustedOrigin(origin: string | null, host: string | null): boolean {
  if (origin === null || origin === '' || host === null || host === '') {
    return false;
  }

  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

export type RateLimitRule = { limit: number; windowMs: number };

export type RateLimitState = { count: number; resetAt: number };

export type RateLimitDecision =
  | { kind: 'allowed'; remaining: number }
  | { kind: 'blocked'; retryAfterSeconds: number };

export const API_RATE_LIMIT: RateLimitRule = { limit: 60, windowMs: 60_000 };

/** 時刻は引数で受け取る（実時間に依存させないため） */
export function decideRateLimit(
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

// ---------------------------------------------------------------------------
// セッション27：TTL 付きのキャッシュとタグ（web の lib/cache-tags.ts と同じ考え方）
// ---------------------------------------------------------------------------

export const PRODUCTS_TAG = 'products';

export function categoryTag(slug: string): string {
  return `category-${slug}`;
}

export type TtlCache<T> = {
  get: (key: string, now: number) => T | undefined;
  set: (key: string, value: T, now: number, tags?: readonly string[]) => void;
  invalidateTag: (tag: string) => number;
  size: () => number;
};

export function createTtlCache<T>(ttlMs: number): TtlCache<T> {
  type Entry = { value: T; expiresAt: number; tags: readonly string[] };

  const store = new Map<string, Entry>();

  return {
    get: (key, now) => {
      const entry = store.get(key);

      if (entry === undefined) {
        return undefined;
      }
      // 期限ちょうどは切れている扱い
      if (entry.expiresAt <= now) {
        store.delete(key);

        return undefined;
      }

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
  };
}
