// 【わざと穴を開けた実装】本章で自分の手で破るために用意した、脆弱な「検証」です。
// 本番のコードにこの形を持ち込まないでください。
import type { JWTPayload } from "jose";
import { createRemoteJWKSet, decodeJwt, decodeProtectedHeader, jwtVerify } from "jose";
import { ISSUER, JWKS_URI } from "./bookstore-endpoints.js";

/**
 * 悪い例 1: デコードしてクレームだけを見る。
 * 期限と発行者を確かめているので「検証した」気になりますが、署名を一度も見ていません。
 */
export function verifyClaimsOnly(token: string): JWTPayload {
  const payload = decodeJwt(token);
  const exp = payload["exp"];
  if (typeof exp === "number" && exp * 1000 < Date.now()) {
    throw new Error("有効期限が切れています");
  }
  if (payload["iss"] !== ISSUER) {
    throw new Error("発行者が違います");
  }
  return payload;
}

/**
 * 悪い例 2: ヘッダの alg を読み、その値に合わせて鍵の使い方を切り替える。
 * 検証方法を「トークン自身の申告」に従って決めているため、申告を書き換えられると破れます。
 */
export async function verifyByHeaderAlg(token: string, keyMaterial: string): Promise<JWTPayload> {
  const header = decodeProtectedHeader(token);
  const alg = typeof header.alg === "string" ? header.alg : "";

  if (alg === "none") {
    // 「署名は無い」と書いてあるので、署名の確認を省いてしまう
    return decodeJwt(token);
  }
  if (alg.startsWith("HS")) {
    // 共通鍵方式だと思い込み、手元の鍵素材をそのまま HMAC の鍵として使う
    const result = await jwtVerify(token, new TextEncoder().encode(keyMaterial));
    return result.payload;
  }
  const result = await jwtVerify(token, createRemoteJWKSet(new URL(JWKS_URI)));
  return result.payload;
}
