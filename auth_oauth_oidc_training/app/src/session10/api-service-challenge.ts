// 401 と 403 の返し方をまとめたモジュール。
// WWW-Authenticate（RFC 6750 §3）に何を書けるか・書けないかをここで一元管理します。
import type { Context } from "hono";

/** チャレンジに書く保護領域の名前。Keycloak の realm（bookstore）とは別物です */
export const REALM_LABEL = "api-service";

/** RFC 6750 が error / error_description に許すのは ASCII の一部だけ（" と \ も禁止） */
const UNSAFE_FOR_HEADER = /[^\x20-\x21\x23-\x5B\x5D-\x7E]/g;

/** ヘッダに入れてよい形に直します。日本語・引用符・改行はここで落ちます */
export function toHeaderSafe(text: string): string {
  return text.replace(UNSAFE_FOR_HEADER, " ").replace(/ {2,}/g, " ").trim();
}

/** RFC 6750 のエラーコード。insufficient_scope はセッション 11 で扱います */
export type BearerErrorCode = "invalid_request" | "invalid_token";

export type Challenge = {
  error?: BearerErrorCode;
  /** 開発者向けの短い説明。ASCII だけ */
  description?: string;
};

/** WWW-Authenticate の値を組み立てます */
export function bearerChallenge(realm: string, challenge: Challenge = {}): string {
  const params = [`realm="${realm}"`];
  if (challenge.error !== undefined) {
    params.push(`error="${challenge.error}"`);
    // ヘッダに入らない文字を落としたうえで、空になったら項目そのものを付けない
    const description = toHeaderSafe(challenge.description ?? "");
    if (description !== "") params.push(`error_description="${description}"`);
  }
  return `Bearer ${params.join(", ")}`;
}

export type UnauthorizedArgs = Challenge & {
  realm?: string;
  /** 利用者に見せる日本語の説明。ヘッダではなく本文に入れます */
  message: string;
};

/** 401: 誰か分からない。WWW-Authenticate で「Bearer で出し直して」と伝えます */
export function unauthorized(c: Context, args: UnauthorizedArgs): Response {
  const { realm = REALM_LABEL, error, description, message } = args;
  c.header("www-authenticate", bearerChallenge(realm, { error, description }));
  // 認証に関わる応答はキャッシュに載せない（別の利用者に配られると事故になります）
  c.header("cache-control", "no-store");
  return c.json({ error: error ?? "unauthenticated", message }, 401);
}

/**
 * 403: 誰かは分かっているが許されない。
 * 認証はできているので WWW-Authenticate は付けません（出し直しても結果が変わらないため）。
 */
export function forbidden(c: Context, message: string): Response {
  c.header("cache-control", "no-store");
  return c.json({ error: "forbidden", message }, 403);
}
