// 問題 3 の解答: 自分で鍵ペアを作ってトークンを発行し、
// クレームの条件だけを 1 つずつ崩して検証結果を比べます。
// 実行: docker compose exec app npx tsx src/session04/api-service-compare-verify.ts
import { jwtVerify } from "jose";
import { AUDIENCE, ISSUER } from "./bookstore-endpoints.js";
import { rejectReason, verifyOptions } from "./api-service-verify-jwt.js";
import { mintTokenWithOwnKey } from "./attacker-forge-tokens.js";

// 発行に使った鍵で検証するので署名は必ず通る。落ちる理由はクレームだけになる
const cases: Array<{ label: string; mint: Parameters<typeof mintTokenWithOwnKey>[0] }> = [
  { label: "別の宛先（aud）に向けたトークン", mint: { issuer: ISSUER, audience: "other-service" } },
  {
    label: "別の発行者（iss）を名乗るトークン",
    mint: { issuer: "http://evil.example.com/realms/bookstore", audience: AUDIENCE },
  },
  {
    label: "有効期限（exp）が過ぎたトークン",
    mint: { issuer: ISSUER, audience: AUDIENCE, issuedAtOffsetSec: -600, expiresInSec: 300 },
  },
  {
    label: "まだ有効になっていない（nbf）トークン",
    mint: { issuer: ISSUER, audience: AUDIENCE, notBeforeOffsetSec: 300, expiresInSec: 600 },
  },
  { label: "すべての条件を満たすトークン", mint: { issuer: ISSUER, audience: AUDIENCE } },
];

console.log("=== 同じ検証条件で 5 種類のトークンを検証する ===");
for (const testCase of cases) {
  const minted = await mintTokenWithOwnKey(testCase.mint);
  try {
    await jwtVerify(minted.token, minted.publicKey, verifyOptions);
    console.log(`- ${testCase.label}: 通過`);
  } catch (err) {
    console.log(`- ${testCase.label}: 拒否（${rejectReason(err)}）`);
  }
}
console.log("どのトークンも署名は正しく、落ちた理由はクレームの内容だけです");
