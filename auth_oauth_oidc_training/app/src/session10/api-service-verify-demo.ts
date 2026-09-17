// 本章の山場（aud を見ないと何が通るか・JWKS に無い鍵で署名されたトークン）を確かめるデモ。
// 実行: docker compose exec app npx tsx src/session10/api-service-verify-demo.ts
import { decodeJwtPart, loginHeadless } from "../test-helpers/headless-login.js";
import { AUDIENCE, ISSUER } from "../session04/bookstore-endpoints.js";
import { mintTokenWithOwnKey } from "../session04/attacker-forge-tokens.js";
import { createApiApp } from "./api-service-app.js";
import { verifyIgnoringAudience } from "./api-service-audience-lab.js";

const strict = createApiApp();
// aud だけ確かめない実装を差し込んだ、同じ API（実験用）
const loose = createApiApp({ verify: verifyIgnoringAudience });

/** /api/whoami を叩いて、status と WWW-Authenticate を 1 行で表示します */
async function show(label: string, app: ReturnType<typeof createApiApp>, authorization?: string) {
  const init = authorization === undefined ? undefined : { headers: { authorization } };
  const res = await app.request("/api/whoami", init);
  console.log(`${label}: ${res.status} ${res.headers.get("www-authenticate") ?? "(WWW-Authenticate なし)"}`);
  return res;
}

const { tokens } = await loginHeadless(); // ブラウザ役はセッション 6 で用意した検証用ヘルパー
const idToken = tokens.id_token ?? "";

console.log("=== 1. 宛先（aud）を確かめないと何が通るか ===");
await show("本物のアクセストークン", strict, `Bearer ${tokens.access_token}`);
await show("ID トークン / aud を検証する", strict, `Bearer ${idToken}`);
const passed = await show("ID トークン / aud を検証しない", loose, `Bearer ${idToken}`);
const body = (await passed.json()) as { subject?: string };
const accessSub = decodeJwtPart<{ sub?: string }>(tokens.access_token, 1).sub;
console.log(`  → sub がアクセストークンと同じ: ${body.subject === accessSub}`);

console.log("\n=== 2. JWKS に無い鍵で署名されたトークン ===");
const own = await mintTokenWithOwnKey({ issuer: ISSUER, audience: AUDIENCE, subject: "attacker" });
await show("自分の鍵で署名したトークン", strict, `Bearer ${own.token}`);
