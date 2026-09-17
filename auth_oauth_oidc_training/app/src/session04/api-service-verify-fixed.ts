// 問題 4・5 の解答: 検証の順序を正し、受け付けるアルゴリズムを固定した実装。
// 実行: docker compose exec app npx tsx src/session04/api-service-verify-fixed.ts
import { AUDIENCE, ISSUER, fetchAccessToken } from "./bookstore-endpoints.js";
import { verifyAccessToken } from "./api-service-verify-jwt.js";
import { forgeNoneToken } from "./attacker-forge-tokens.js";

// 利用者テーブルの代わり。問い合わせ回数を数えて、副作用がいつ起きたかを目に見えるようにします
let databaseCallCount = 0;
function loadUserFromDatabase(subject: string): { subject: string; displayName: string } {
  databaseCallCount += 1;
  return { subject, displayName: `利用者(${subject.slice(0, 4)}…)` };
}

/**
 * 正しい順序: 署名 → iss → aud → 時刻 をすべて通してから、初めて sub を使う。
 * 検証前に副作用（DB 問い合わせ・ログ出力・レコード作成）を起こさないことが要点です。
 */
async function handleRequest(token: string): Promise<{ subject: string; displayName: string }> {
  // 1. ここで署名・iss・aud・時刻がまとめて検証される（1 つでも欠ければ例外）
  const { payload } = await verifyAccessToken(token);

  // 2. 検証を通ったので、ここから先のクレームは「認可サーバーが言ったこと」として扱える
  const subject = payload["sub"];
  if (typeof subject !== "string" || subject === "") {
    throw new Error("sub が入っていないトークンです");
  }

  // 3. 副作用はすべて検証の後ろに置く
  return loadUserFromDatabase(subject);
}

const token = await fetchAccessToken();

console.log("=== 修正版: 署名検証を通ってから初めて sub を使う ===");
const user = await handleRequest(token);
console.log(`[本物のトークン] 利用者レコードを引けた: ${user.subject.length > 0}`);

const nowSec = Math.floor(Date.now() / 1000);
const forged = forgeNoneToken({
  iss: ISSUER,
  sub: "attacker",
  aud: AUDIENCE,
  iat: nowSec,
  exp: nowSec + 300,
});
try {
  await handleRequest(forged);
  console.log("[alg: none の偽造トークン] 通ってしまった（実装を見直してください）");
} catch {
  console.log("[alg: none の偽造トークン] 拒否されました");
}

console.log(`データベースへの問い合わせ回数: ${databaseCallCount}`);
console.log("偽造トークンのリクエストは、データベースにも監査ログにも一切触れていません");
