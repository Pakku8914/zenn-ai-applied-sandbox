// セッション 16 の共通設定。
// 鍵には「公開されている姿」（JWKS）と「認可サーバー内部の姿」（Admin REST API）があり、
// 載っているものが一致しません。両方を読める道具をここにまとめます。
import { createLocalJWKSet, jwtVerify } from "jose";
import type { JSONWebKeySet, JWTPayload } from "jose";
import { ISSUER, JWKS_URI } from "../session04/bookstore-endpoints.js";
import { verifyOptions } from "../session04/api-service-verify-jwt.js";

export { ISSUER, JWKS_URI };
export const REALM = "bookstore";
/** realm を含まない Keycloak 本体の URL（Admin REST API で使う） */
export const KEYCLOAK_BASE_INTERNAL = ISSUER.replace(/\/realms\/[^/]+$/, "");

/** JWKS に載っている 1 本の鍵。use は "sig"（署名検証用）か "enc"（暗号用） */
export type PublishedKey = { readonly kid: string; readonly use: string; readonly alg: string };

/** 内部から見た鍵。use は "SIG"/"ENC"、status は "ACTIVE"/"PASSIVE"/"DISABLED"（JWKS と表記が違う） */
export type ManagedKey = {
  readonly kid: string;
  readonly use: string;
  readonly algorithm: string;
  readonly status: string;
};

const asString = (value: unknown): string => (typeof value === "string" ? value : "");
const asRecord = (value: unknown): Record<string, unknown> =>
  (typeof value === "object" && value !== null ? value : {}) as Record<string, unknown>;
const keysIn = (body: unknown): unknown[] => {
  const list = asRecord(body)["keys"];
  return Array.isArray(list) ? list : [];
};

/** JWKS を生のまま取ります。「いま取った鍵束」を変数として持てるようにするのが目的です */
export async function fetchJwks(): Promise<JSONWebKeySet> {
  const res = await fetch(JWKS_URI);
  if (!res.ok) throw new Error(`JWKS の取得に失敗しました: HTTP ${res.status}`);
  return (await res.json()) as JSONWebKeySet;
}

/** JWKS の鍵を、型のそろった一覧にして返します */
export async function fetchPublishedKeys(): Promise<PublishedKey[]> {
  return keysIn(await fetchJwks()).map((key) => {
    const k = asRecord(key);
    return { kid: asString(k["kid"]), use: asString(k["use"]), alg: asString(k["alg"]) };
  });
}

/** 署名検証に使える鍵だけを残します（暗号用の鍵は検証には使えません） */
export function signingKeys(keys: readonly PublishedKey[], alg: string = "RS256"): PublishedKey[] {
  return keys.filter((key) => key.use === "sig" && key.alg === alg);
}

/** 検証側が「選べる鍵」の識別子の一覧 */
export function kidsOf(keys: readonly PublishedKey[]): string[] {
  return keys.map((key) => key.kid).filter((kid) => kid !== "");
}

/**
 * 渡した鍵束だけで検証します（ネットワークに出ません）。
 * 検証の条件はセッション 4 の verifyOptions をそのまま使います。変えていないことが重要です。
 */
export async function verifyWithKeySet(token: string, jwks: JSONWebKeySet): Promise<JWTPayload> {
  const { payload } = await jwtVerify(token, createLocalJWKSet(jwks), verifyOptions);
  return payload;
}

/** 管理者トークン。expires_in は 60 秒なので、長い手順では取り直す前提で使います */
export async function fetchAdminToken(): Promise<string> {
  const res = await fetch(`${KEYCLOAK_BASE_INTERNAL}/realms/master/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    // サンドボックス専用の固定値。本番では環境変数や Secret Manager から読みます
    body: new URLSearchParams({
      grant_type: "password",
      client_id: "admin-cli",
      username: "admin",
      password: "admin",
    }),
  });
  if (!res.ok) throw new Error(`管理者トークンの取得に失敗しました: HTTP ${res.status}`);
  return ((await res.json()) as { access_token: string }).access_token;
}

export async function adminFetch(
  token: string,
  path: string,
  init: { method?: string; body?: unknown } = {},
): Promise<Response> {
  const { method = "GET", body } = init;
  return fetch(`${KEYCLOAK_BASE_INTERNAL}/admin${path}`, {
    method,
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

/** 内部の鍵一覧。JWKS に出てこない鍵（対称鍵）もここには出ます */
export async function fetchManagedKeys(token: string): Promise<ManagedKey[]> {
  const res = await adminFetch(token, `/realms/${REALM}/keys`);
  if (!res.ok) throw new Error(`鍵の一覧の取得に失敗しました: HTTP ${res.status}`);
  return keysIn(await res.json()).map((key) => {
    const k = asRecord(key);
    return {
      kid: asString(k["kid"]),
      use: asString(k["use"]),
      algorithm: asString(k["algorithm"]),
      status: asString(k["status"]),
    };
  });
}

/** いま署名に使われうる鍵（内部の姿）。ACTIVE で SIG のものだけ */
export function activeSigningKeys(keys: readonly ManagedKey[]): ManagedKey[] {
  return keys.filter((key) => key.use === "SIG" && key.status === "ACTIVE");
}
