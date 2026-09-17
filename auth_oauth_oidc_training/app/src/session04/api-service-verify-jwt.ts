// リソースサーバー（api-service）が受け取ったトークンを検証する、本章の「正解」の実装。
import { createRemoteJWKSet, jwtVerify } from "jose";
import { AUDIENCE, ISSUER, JWKS_URI } from "./bookstore-endpoints.js";

// JWKS の取得口は 1 回だけ作って使い回します（jose が取得結果をキャッシュします）
const jwks = createRemoteJWKSet(new URL(JWKS_URI));

/** api-service がトークンに求める条件。1 つでも省くと穴が開きます */
export const verifyOptions = {
  algorithms: ["RS256"], // ヘッダの alg を信じず、受け付ける方式を固定する
  issuer: ISSUER, // 誰が発行したトークンか
  audience: AUDIENCE, // 自分宛てのトークンか
  clockTolerance: 5, // 時計のずれの許容（秒）
};

/** 署名 → iss → aud → 時刻 の順に検証し、信用してよいクレームを返します */
export async function verifyAccessToken(token: string) {
  return await jwtVerify(token, jwks, verifyOptions);
}

// jose が投げるエラーの code を、日本語の短い理由に対応づけます
const REASONS: Record<string, string> = {
  ERR_JWS_SIGNATURE_VERIFICATION_FAILED: "署名が鍵と一致しない",
  ERR_JWT_EXPIRED: "有効期限が切れている",
  ERR_JWKS_NO_MATCHING_KEY: "署名に使われた鍵が JWKS に無い",
  ERR_JOSE_ALG_NOT_ALLOWED: "許可していない署名アルゴリズム",
  ERR_JOSE_NOT_SUPPORTED: "jose が扱わない署名アルゴリズム",
  ERR_JWT_INVALID: "JWT の形式ではない",
};

/** 検証が失敗した理由を 1 行で説明します（ログ用。クライアントには返しません） */
export function rejectReason(err: unknown): string {
  const e = (typeof err === "object" && err !== null ? err : {}) as {
    code?: unknown;
    claim?: unknown;
  };
  const code = typeof e.code === "string" ? e.code : "";
  if (code === "ERR_JWT_CLAIM_VALIDATION_FAILED") {
    return `クレームの検証に失敗（${typeof e.claim === "string" ? e.claim : "不明"}）`;
  }
  return REASONS[code] ?? `その他の失敗（${code === "" ? "コードなし" : code}）`;
}
