/**
 * 運用のための 2 つの部品 ―― 監査ログとレート制限
 *
 * 出力先は既定で stderr です。stdout は stdio トランスポートでは通信路そのものなので、
 * 監査ログ 1 行で電文が壊れます（HTTP でも同じコードを使うため、統一しておきます）。
 *
 * セッション15 との違い：1 プロセスが複数セッション・複数利用者を扱うので、
 * 誰の操作かを表す actor を「ロガー生成時」ではなく「write 時」に渡します。
 */
import { createHmac } from "node:crypto";

export type AuditEvent =
  | "tool_call"
  | "resource_read"
  | "prompt_get"
  | "rate_limited"
  | "internal_error";

export type AuditOutcome = "ok" | "rejected" | "error";

/** ログに載せてよい型だけを許す。巨大な生文字列を渡しにくくするための縛り */
export type AuditParams = Readonly<Record<string, number | boolean | string>>;

export type AuditActor = {
  readonly tenantId: string;
  readonly subjectId: string;
  readonly tokenRef: string;
};

export type AuditInput = {
  readonly event: AuditEvent;
  readonly target: string;
  readonly outcome: AuditOutcome;
  readonly actor: AuditActor;
  readonly params?: AuditParams;
  readonly reason?: string;
  readonly resultCount?: number;
  readonly durationMs?: number;
};

export type AuditLoggerOptions = {
  readonly server: string;
  /** HMAC の鍵（ペッパー）。ハッシュだけでは短い値を総当たりされる */
  readonly pepper: string;
  readonly clock?: () => number;
  readonly sink?: (line: string) => void;
  readonly knownSecrets?: readonly string[];
};

export type AuditLogger = {
  write(input: AuditInput): void;
  /** 生値の代わりに載せる参照値。同じ入力なら同じ値になるので追跡できる */
  ref(value: string): string;
};

export const REDACTED = "[REDACTED]";
const MAX_FIELD_LENGTH = 200;

/** 既知の秘密値を知らなくても網に掛ける最後の砦 */
export const SECRET_PATTERNS: readonly RegExp[] = [
  /gh[pousr]_[A-Za-z0-9]{16,}/g,
  /sk-[A-Za-z0-9_-]{16,}/g,
  /AKIA[0-9A-Z]{16}/g,
  /eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/g,
];

export function scrubSecrets(text: string, knownSecrets: readonly string[] = []): string {
  let out = text;
  for (const secret of knownSecrets) {
    // 短い値を置換対象にすると、無関係な文字列まで [REDACTED] になる
    if (secret.length >= 8) out = out.split(secret).join(REDACTED);
  }
  for (const pattern of SECRET_PATTERNS) out = out.replace(pattern, REDACTED);
  return out;
}

/** 制御文字を空白にする。改行が残るとログ 1 行を偽造できる */
function flattenControlChars(value: string): string {
  let out = "";
  for (const character of value) {
    const codePoint = character.codePointAt(0) ?? 0;
    out += codePoint <= 0x1f || codePoint === 0x7f ? " " : character;
  }
  return out;
}

function scrubField(value: string, knownSecrets: readonly string[]): string {
  const flattened = flattenControlChars(scrubSecrets(value, knownSecrets)).trim();
  const points = [...flattened];
  return points.length > MAX_FIELD_LENGTH
    ? `${points.slice(0, MAX_FIELD_LENGTH).join("")}…`
    : flattened;
}

export function createAuditLogger(options: AuditLoggerOptions): AuditLogger {
  const clock = options.clock ?? (() => Date.now());
  const sink = options.sink ?? ((line: string) => void process.stderr.write(`${line}\n`));
  const knownSecrets = options.knownSecrets ?? [];

  const ref = (value: string): string =>
    createHmac("sha256", options.pepper).update(value).digest("hex").slice(0, 16);

  function write(input: AuditInput): void {
    const params: Record<string, number | boolean | string> = {};
    for (const [key, value] of Object.entries(input.params ?? {})) {
      params[key] = typeof value === "string" ? scrubField(value, knownSecrets) : value;
    }

    const record = {
      ts: new Date(clock()).toISOString(),
      server: options.server,
      tenantId: input.actor.tenantId,
      subject: ref(input.actor.subjectId),
      tokenRef: input.actor.tokenRef,
      event: input.event,
      target: scrubField(input.target, knownSecrets),
      outcome: input.outcome,
      params,
      ...(input.reason === undefined ? {} : { reason: scrubField(input.reason, knownSecrets) }),
      ...(input.resultCount === undefined ? {} : { resultCount: input.resultCount }),
      ...(input.durationMs === undefined ? {} : { durationMs: input.durationMs }),
    };

    // JSON.stringify は改行やクォートをエスケープするので、1 レコードが必ず 1 行になる
    sink(JSON.stringify(record));
  }

  return { write, ref };
}

// ---------------------------------------------------------------------------
// レート制限（トークンバケット）
// ---------------------------------------------------------------------------

export type RateLimitDecision =
  | { readonly allowed: true; readonly remaining: number }
  | { readonly allowed: false; readonly retryAfterMs: number };

export type RateLimiterOptions = {
  readonly capacity: number;
  readonly refillPerSecond: number;
  /** ★ 時計は必ず注入する。内部で Date.now() を呼ぶとテストが実時間を待つことになる */
  readonly now: () => number;
  readonly maxKeys?: number;
};

export type RateLimiter = {
  tryConsume(key: string, cost?: number): RateLimitDecision;
  size(): number;
};

export const DEFAULT_MAX_KEYS = 1000;

export function createRateLimiter(options: RateLimiterOptions): RateLimiter {
  const { capacity, refillPerSecond, now } = options;
  const maxKeys = options.maxKeys ?? DEFAULT_MAX_KEYS;
  const buckets = new Map<string, { tokens: number; updatedAt: number }>();

  function evictOldest(): void {
    let oldestKey: string | undefined;
    let oldestAt = Number.POSITIVE_INFINITY;
    for (const [key, bucket] of buckets) {
      if (bucket.updatedAt < oldestAt) {
        oldestAt = bucket.updatedAt;
        oldestKey = key;
      }
    }
    if (oldestKey !== undefined) buckets.delete(oldestKey);
  }

  function tryConsume(key: string, cost = 1): RateLimitDecision {
    const at = now();
    const current = buckets.get(key);
    if (current === undefined && buckets.size >= maxKeys) evictOldest();
    const bucket = current ?? { tokens: capacity, updatedAt: at };
    const elapsedMs = Math.max(0, at - bucket.updatedAt);
    const tokens = Math.min(capacity, bucket.tokens + (elapsedMs / 1000) * refillPerSecond);

    if (tokens < cost) {
      // 残量を更新しておく（次回の判定で二重に回復させないため）
      buckets.set(key, { tokens, updatedAt: at });
      return {
        allowed: false,
        retryAfterMs: Math.ceil(((cost - tokens) / refillPerSecond) * 1000),
      };
    }
    buckets.set(key, { tokens: tokens - cost, updatedAt: at });
    return { allowed: true, remaining: Math.floor(tokens - cost) };
  }

  return { tryConsume, size: () => buckets.size };
}
