// 認証・認可の監査ログ。「何を書くか」より「何を書かないか」が設計の中心です。
// 書いてしまった秘密はログ基盤・バックアップ・転送先のすべてに複製されるので、
// 落とすのは出力の直前ではなく、記録を組み立てる場所でなければなりません。
import type { JWTPayload } from "jose";
import { audiencesOf } from "../session10/api-service-claims.js";

/** 記録してよい項目だけを並べた型。ここに無いものは記録しません */
export type AuditEvent = {
  /** 時刻。ISO 8601（UTC）で固定します */
  readonly at: string;
  readonly event: "token.accepted" | "token.rejected" | "authz.granted" | "authz.denied";
  /** 誰か。表示名ではなく、認可サーバーが決めた不変の識別子 */
  readonly sub: string;
  /** どの認可サーバーが発行したトークンか */
  readonly iss: string;
  /** トークン 1 本の識別子。トークン本体の代わりにこれを記録します */
  readonly jti: string;
  /** どのクライアント経由か（アクセストークンの azp） */
  readonly clientId: string;
  readonly audience: readonly string[];
  readonly decision: "allow" | "deny";
  /** 運用で読む理由。クライアントに返す文面とは別です */
  readonly reason: string;
  readonly ip: string;
};

/** 値を見ずに名前だけで落とすキー。小文字で比べます */
export const FORBIDDEN_KEYS: readonly string[] = [
  "access_token",
  "refresh_token",
  "id_token",
  "authorization",
  "cookie",
  "set-cookie",
  "password",
  "client_secret",
  "code",
  "code_verifier",
  "client_assertion",
];

export const REDACTED = "<redacted>";

/** 秘密は長さだけ残します。先頭数文字も残しません（短い秘密ほど致命的です） */
export function maskSecret(value: string): string {
  return `${REDACTED} len=${value.length}`;
}

/** JWT らしい値か。禁止キーの一覧から漏れたキーに秘密が入っていても、値の形で捕まえます */
export function looksLikeJwt(value: string): boolean {
  return /(^|\s)(Bearer\s+)?eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\./.test(value);
}

/** 記録を安全な形に直します。名前で落とし、残りを値で最終確認します */
export function redact(record: Readonly<Record<string, unknown>>): Record<string, unknown> {
  const safe: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(record)) {
    if (FORBIDDEN_KEYS.includes(key.toLowerCase())) {
      safe[key] = typeof value === "string" ? maskSecret(value) : REDACTED;
    } else if (typeof value === "string" && looksLikeJwt(value)) {
      safe[key] = maskSecret(value);
    } else {
      safe[key] = value;
    }
  }
  return safe;
}

const asString = (value: unknown): string => (typeof value === "string" ? value : "");

/** 検証に使う時刻と接続元。Keycloak の監査イベントにも ipAddress が記録されます */
export type AuditContext = { readonly now?: Date; readonly ip?: string };

export type Outcome = {
  readonly event: AuditEvent["event"];
  readonly decision: AuditEvent["decision"];
  readonly reason: string;
};

/**
 * 検証を通ったクレームから、記録してよい項目だけを抜き出します。
 * ペイロード全体を展開しないこと自体が対策です（クレームは将来増えます）。
 */
export function auditFromClaims(payload: JWTPayload, outcome: Outcome, ctx: AuditContext = {}): AuditEvent {
  const claims = payload as Record<string, unknown>;
  return {
    at: (ctx.now ?? new Date()).toISOString(),
    event: outcome.event,
    sub: asString(claims["sub"]),
    iss: asString(claims["iss"]),
    jti: asString(claims["jti"]),
    clientId: asString(claims["azp"]),
    audience: audiencesOf(payload),
    decision: outcome.decision,
    reason: outcome.reason,
    ip: ctx.ip ?? "",
  };
}

/**
 * 検証に失敗したときの記録。クレームを信用できないので、
 * トークンから読み取った値は載せません（誰かは分からないまま記録します）。
 */
export function auditRejection(reason: string, ctx: AuditContext = {}): AuditEvent {
  return {
    at: (ctx.now ?? new Date()).toISOString(),
    event: "token.rejected",
    sub: "",
    iss: "",
    jti: "",
    clientId: "",
    audience: [],
    decision: "deny",
    reason,
    ip: ctx.ip ?? "",
  };
}

/** 1 行 1 イベントの JSON。あとで検索できる形にしておくのが監査ログの最低条件です */
export function formatLine(event: AuditEvent): string {
  return JSON.stringify(event);
}
