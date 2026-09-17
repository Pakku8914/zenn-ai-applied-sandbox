/**
 * 監査ログ ―― 誰がどのツールをどの引数で呼んだかを、秘密情報と生値を落として記録する
 *
 * 出力先は既定で stderr です。stdout に書いてはいけません。stdio トランスポートでは
 * stdout が JSON-RPC の通信路そのものなので、ログ 1 行で電文が壊れ、ホストからは
 * 「サーバーが壊れた」ようにしか見えません（原因の特定が非常に難しい事故になります）。
 * 実運用ではファイル（またはログ収集エージェントの入力）へ向けます。
 */
import { createHmac } from "node:crypto";

export type AuditEvent =
  | "tool_call"
  | "resource_read"
  | "prompt_get"
  | "rate_limited"
  | "auth_failed"
  | "internal_error";

export type AuditOutcome = "ok" | "rejected" | "error";

/** ログに載せてよい型だけを許す。生の巨大文字列を渡しにくくするための縛り */
export type AuditParams = Readonly<Record<string, number | boolean | string>>;

export type AuditInput = {
  readonly event: AuditEvent;
  readonly target: string;
  readonly outcome: AuditOutcome;
  readonly params?: AuditParams;
  readonly reason?: string;
  readonly resultCount?: number;
  readonly findings?: readonly string[];
  readonly durationMs?: number;
};

export type AuditLoggerOptions = {
  readonly server: string;
  readonly tenantId: string;
  readonly subjectId: string;
  readonly sessionId: string;
  /** HMAC の鍵（ペッパー）。ハッシュだけでは短い値を総当たりされる */
  readonly pepper: string;
  readonly clock?: () => number;
  readonly sink?: (line: string) => void;
  /** ログから取り除く既知の秘密値（トークンなど） */
  readonly knownSecrets?: readonly string[];
};

export type AuditLogger = {
  write(input: AuditInput): void;
  /** 生値の代わりに載せる参照値。同じ入力なら同じ値になるので追跡できる */
  hash(value: string): string;
};

export const REDACTED = "[REDACTED]";
const MAX_FIELD_LENGTH = 200;

/** トークンらしい文字列。既知の秘密値を知らなくても網に掛ける（最後の砦） */
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
    if (secret.length >= 8) {
      out = out.split(secret).join(REDACTED);
    }
  }
  for (const pattern of SECRET_PATTERNS) {
    out = out.replace(pattern, REDACTED);
  }
  return out;
}

/**
 * 制御文字を空白に置き換える。改行が残ると、値に改行を混ぜてログ 1 行を偽造できます。
 * コードポイントで判定しているのは、正規表現に制御文字を直接書くと
 * ソースコードが読めなくなる（レビューできなくなる）ためです。
 */
function flattenControlChars(value: string): string {
  let out = "";
  for (const character of value) {
    const codePoint = character.codePointAt(0) ?? 0;
    out += codePoint <= 0x1f || codePoint === 0x7f ? " " : character;
  }
  return out;
}

/** ログ 1 行に入れる文字列の共通処理。制御文字を消してログ行の偽装を防ぐ */
function scrubField(value: string, knownSecrets: readonly string[]): string {
  const flattened = flattenControlChars(scrubSecrets(value, knownSecrets)).trim();
  const points = [...flattened];
  return points.length > MAX_FIELD_LENGTH
    ? `${points.slice(0, MAX_FIELD_LENGTH).join("")}…`
    : flattened;
}

export function createAuditLogger(options: AuditLoggerOptions): AuditLogger {
  const clock = options.clock ?? (() => Date.now());
  const sink =
    options.sink ??
    ((line: string) => {
      // stdout は JSON-RPC の通信路。監査ログは必ず stderr かファイルへ
      process.stderr.write(`${line}\n`);
    });
  const knownSecrets = options.knownSecrets ?? [];

  function hash(value: string): string {
    return createHmac("sha256", options.pepper).update(value).digest("hex").slice(0, 16);
  }

  function write(input: AuditInput): void {
    const params: Record<string, number | boolean | string> = {};
    for (const [key, value] of Object.entries(input.params ?? {})) {
      params[key] = typeof value === "string" ? scrubField(value, knownSecrets) : value;
    }

    const record = {
      ts: new Date(clock()).toISOString(),
      server: options.server,
      tenantId: options.tenantId,
      subject: hash(options.subjectId),
      // セッションID も持ち出されると成りすましに使われうる。参照値にする
      sessionRef: hash(options.sessionId),
      event: input.event,
      target: scrubField(input.target, knownSecrets),
      outcome: input.outcome,
      params,
      ...(input.reason === undefined ? {} : { reason: scrubField(input.reason, knownSecrets) }),
      ...(input.resultCount === undefined ? {} : { resultCount: input.resultCount }),
      ...(input.findings === undefined ? {} : { findings: [...input.findings] }),
      ...(input.durationMs === undefined ? {} : { durationMs: input.durationMs }),
    };

    // JSON.stringify は改行やクォートをエスケープするので、1 レコードが必ず 1 行になる。
    // 手で "key=value" を組み立てると、改行を含む値でログ行を偽造できてしまう
    sink(JSON.stringify(record));
  }

  return { write, hash };
}
