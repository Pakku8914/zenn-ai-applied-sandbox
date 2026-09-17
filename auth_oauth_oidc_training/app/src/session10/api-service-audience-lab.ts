// 「宛先（aud）だけを確かめない検証」を用意して、何が通ってしまうかを実測する実験用のコード。
// 同梱サンドボックスの中の自分のコードに対してだけ使います。本番のコードに持ち込まないこと。
import { createRemoteJWKSet, jwtVerify } from "jose";
import type { JWTPayload } from "jose";
import { ISSUER, JWKS_URI } from "../session04/bookstore-endpoints.js";

// 実験用なので、本番の検証とは別の JWKS 取得口を持たせます
const jwks = createRemoteJWKSet(new URL(JWKS_URI));

/**
 * 署名・iss・時刻は正しく確かめるが、audience だけ渡さない検証。
 * 「同じ認可サーバーが出したトークンなら何でも受け取る」実装がこれにあたります。
 */
export async function verifyIgnoringAudience(token: string): Promise<JWTPayload> {
  const { payload } = await jwtVerify(token, jwks, {
    algorithms: ["RS256"],
    issuer: ISSUER,
    clockTolerance: 5,
    // audience を指定していない ← ここが穴
  });
  return payload;
}
