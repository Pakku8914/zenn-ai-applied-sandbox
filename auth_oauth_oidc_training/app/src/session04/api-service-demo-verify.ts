// 実行: docker compose exec app npx tsx src/session04/api-service-demo-verify.ts
// 正しいトークンが通ること、改ざんされたトークンが必ず落ちることを確かめます。
import { AUDIENCE, fetchAccessToken } from "./bookstore-endpoints.js";
import { audienceList } from "./api-service-jwt-parts.js";
import { rejectReason, verifyAccessToken } from "./api-service-verify-jwt.js";
import { verifyClaimsOnly } from "./api-service-verify-insecure.js";
import { tamperPayload } from "./attacker-forge-tokens.js";

const token = await fetchAccessToken();

console.log("=== 1. 正しいトークンを正しい順序で検証する ===");
const { payload, protectedHeader } = await verifyAccessToken(token);
console.log(`署名アルゴリズム: ${String(protectedHeader.alg)}`);
console.log(`iss: ${String(payload["iss"])}`);
console.log(`azp: ${String(payload["azp"])}`);
console.log(`aud に ${AUDIENCE} を含む: ${audienceList(payload).includes(AUDIENCE)}`);

// 署名は本物のまま、ペイロードの sub だけ別人に書き換えたトークンを作る
const tampered = tamperPayload(token, { sub: "attacker" });

console.log("\n=== 2. 同じ改ざんトークンを 2 つの関数に通す ===");
try {
  await verifyAccessToken(tampered);
  console.log("- 厳格な検証: 通ってしまった（実装を見直してください）");
} catch (err) {
  console.log(`- 厳格な検証: 拒否（${rejectReason(err)}）`);
}
console.log(`- デコードだけの検証: 通過（sub: ${String(verifyClaimsOnly(tampered)["sub"])}）`);
console.log("署名を見ない関数は、書き換えられた名前をそのまま信用してしまいました");
