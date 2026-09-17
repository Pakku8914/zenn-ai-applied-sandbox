// リソースサーバー（api-service）が扱うクレームの型と、クレームを読み出す道具。
// 本章が扱うのは「トークンが本物か」「誰宛てか」まで。
// 「誰に何を許すか」の設計はセッション 11 の担当です。
import type { JWTPayload } from "jose";

/**
 * 検証を通ったアクセストークンのクレーム。
 * iss・sub・exp は検証後に必ず使うので必須、それ以外は任意にしてあります。
 */
export interface AccessTokenClaims extends JWTPayload {
  iss: string;
  sub: string;
  exp: number;
  azp?: string;
  scope?: string;
  preferred_username?: string;
  realm_access?: { roles?: string[] };
}

/** Hono のコンテキストに載せる値の型。これを書くと c.get("claims") に型が付きます */
export type ApiEnv = {
  Variables: {
    claims: AccessTokenClaims;
  };
};

/** 検証済みのペイロードを AccessTokenClaims に絞り込みます（欠けていたら例外） */
export function toAccessTokenClaims(payload: JWTPayload): AccessTokenClaims {
  const { iss, sub, exp } = payload;
  if (typeof iss !== "string" || typeof sub !== "string" || typeof exp !== "number") {
    throw new Error("iss・sub・exp のいずれかが入っていないトークンです");
  }
  return payload as AccessTokenClaims;
}

/**
 * aud を必ず配列にそろえます。
 * web-app のトークンは "api-service"（文字列）、batch-worker のトークンは
 * ["api-service","account"]（配列）で届きます。RFC 7519 はどちらの形も許すので、
 * 受け取る側が形をそろえてから比べます。
 */
export function audiencesOf(payload: JWTPayload): string[] {
  const aud = payload.aud;
  if (typeof aud === "string") return [aud];
  if (Array.isArray(aud)) return [...aud];
  return [];
}

/** realm ロールの一覧。トークンに入っていなければ空配列を返します */
export function rolesOf(claims: AccessTokenClaims | undefined): string[] {
  const roles = claims?.realm_access?.roles;
  return Array.isArray(roles) ? [...roles] : [];
}

export function hasRealmRole(claims: AccessTokenClaims | undefined, role: string): boolean {
  return rolesOf(claims).includes(role);
}
