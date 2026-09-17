// Bearer トークンを取り出して検証するミドルウェア。
// 検証をここに集約するのが目的です（ハンドラごとに書くと、書き忘れた 1 本が穴になります）。
import { createMiddleware } from "hono/factory";
import type { JWTPayload } from "jose";
import { rejectReason, verifyAccessToken } from "../session04/api-service-verify-jwt.js";
import { hasRealmRole, toAccessTokenClaims } from "./api-service-claims.js";
import type { AccessTokenClaims, ApiEnv } from "./api-service-claims.js";
import { REALM_LABEL, forbidden, unauthorized } from "./api-service-challenge.js";

/** Authorization: Bearer <token> の形だけを受け付けます（RFC 6750 §2.1 の b64token） */
const BEARER_TOKEN = /^Bearer +([A-Za-z0-9\-._~+/]+=*)$/i;

export type Extracted = { ok: true; token: string } | { ok: false; reason: "missing" | "malformed" };

/** ヘッダ 1 行を「トークン」「無い」「形が壊れている」の 3 つに分けます */
export function extractBearerToken(header: string | undefined): Extracted {
  const value = (header ?? "").trim();
  // 空、または Bearer 以外のスキーム（Basic など）は「Bearer の資格情報が無い」として扱う
  if (value === "" || !/^Bearer($| )/i.test(value)) return { ok: false, reason: "missing" };
  const token = BEARER_TOKEN.exec(value)?.[1];
  return token === undefined ? { ok: false, reason: "malformed" } : { ok: true, token };
}

export type TokenVerifier = (token: string) => Promise<JWTPayload>;

export type BearerAuthOptions = {
  /** 既定はセッション 4 で作った厳格な検証。差し替えるのは実験のときだけです */
  verify?: TokenVerifier;
  realm?: string;
};

const strictVerify: TokenVerifier = async (token) => (await verifyAccessToken(token)).payload;

/** クライアントに返してよい ASCII の短い説明。例外の message をそのまま返してはいけません */
const DESCRIPTIONS: Record<string, string> = {
  ERR_JWT_EXPIRED: "The access token expired",
  ERR_JWS_SIGNATURE_VERIFICATION_FAILED: "The signature does not match the signing key",
  ERR_JWKS_NO_MATCHING_KEY: "The signing key is not published in the JWKS",
  ERR_JOSE_ALG_NOT_ALLOWED: "The signing algorithm is not accepted",
  ERR_JWT_INVALID: "The credentials are not a JWT",
};

/** 失敗の種類を、ヘッダに書ける 1 行に対応づけます */
export function descriptionFor(err: unknown): string {
  const e = (typeof err === "object" && err !== null ? err : {}) as { code?: unknown; claim?: unknown };
  const code = typeof e.code === "string" ? e.code : "";
  if (code === "ERR_JWT_CLAIM_VALIDATION_FAILED") {
    return `The ${typeof e.claim === "string" ? e.claim : "required"} claim did not match`;
  }
  return DESCRIPTIONS[code] ?? "The access token is not valid";
}

/** 検証に成功したらクレームをコンテキストに載せ、失敗したら 401 を返します */
export function bearerAuth(options: BearerAuthOptions = {}) {
  const verify = options.verify ?? strictVerify;
  const realm = options.realm ?? REALM_LABEL;

  return createMiddleware<ApiEnv>(async (c, next) => {
    const extracted = extractBearerToken(c.req.header("authorization"));
    if (!extracted.ok) {
      if (extracted.reason === "missing") {
        // RFC 6750: 資格情報が無いリクエストには error を付けない（まだ何も間違っていない）
        return unauthorized(c, { realm, message: "アクセストークンが必要です" });
      }
      return unauthorized(c, {
        realm,
        error: "invalid_request",
        description: "The Authorization header is not in the Bearer <token> form",
        message: "Authorization ヘッダの形式が正しくありません",
      });
    }

    let claims: AccessTokenClaims;
    try {
      claims = toAccessTokenClaims(await verify(extracted.token));
    } catch (err) {
      // 詳しい理由はログにだけ残す。クライアントに返すのは ASCII の短い説明だけ
      console.warn(`[api-service] 401 invalid_token: ${rejectReason(err)}`);
      return unauthorized(c, {
        realm,
        error: "invalid_token",
        description: descriptionFor(err),
        message: "アクセストークンを受け付けられません",
      });
    }

    // ここから先のハンドラは「検証済みのクレーム」だけを見ればよい
    c.set("claims", claims);
    await next();
  });
}

/**
 * realm ロールを 1 つ要求します。認証済みであることが前提なので、
 * 必ず bearerAuth() のうしろに置いてください。
 */
export function requireRealmRole(role: string) {
  return createMiddleware<ApiEnv>(async (c, next) => {
    const claims: AccessTokenClaims | undefined = c.get("claims");
    if (claims === undefined) {
      // ミドルウェアの順序の誤り。クライアントのせいにしてはいけないので 401 にはしない
      throw new Error("bearerAuth() より先に requireRealmRole() が実行されています");
    }
    if (!hasRealmRole(claims, role)) {
      return forbidden(c, `この操作には ${role} ロールが必要です`);
    }
    await next();
  });
}
