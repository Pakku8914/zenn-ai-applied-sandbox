// 問題 1 の解答: トークンの解剖レポート。
// 実行: docker compose exec app npx tsx src/session04/api-service-claim-report.ts
// 検証（jwtVerify）は使いません。デコードだけでどこまで読めるかを確かめるためのスクリプトです。
import { AUDIENCE, fetchAccessToken } from "./bookstore-endpoints.js";
import { audienceList, decodeParts, lifetimeSeconds } from "./api-service-jwt-parts.js";

/** 値そのものは表示せず、「あるか・ないか」だけを報告します（実行ごとに変わる値だから） */
function presence(payload: Record<string, unknown>, claim: string, hideValue: boolean): string {
  if (payload[claim] === undefined) {
    return "なし";
  }
  return hideValue ? "あり（値は環境ごとに変わるため非表示）" : "あり";
}

const token = await fetchAccessToken();
const { header, payload } = decodeParts(token);

console.log("=== アクセストークンの解剖レポート ===");
console.log(`部品の数: ${token.split(".").length}`);
console.log(`alg: ${String(header["alg"])}`);
console.log(`kid: ${presence(header, "kid", true)}`);
console.log(`iss: ${String(payload["iss"])}`);
console.log(`sub: ${presence(payload, "sub", true)}`);
console.log(`aud に ${AUDIENCE} を含む: ${audienceList(payload).includes(AUDIENCE)}`);
console.log(`exp: ${presence(payload, "exp", false)}`);
console.log(`iat: ${presence(payload, "iat", false)}`);
console.log(`nbf: ${presence(payload, "nbf", false)}`);
console.log(`jti: ${presence(payload, "jti", true)}`);
console.log(`有効期間（exp - iat）: ${String(lifetimeSeconds(payload))} 秒`);
console.log("ここまで鍵は 1 つも使っていません。つまり、この情報は誰にでも読めます");
