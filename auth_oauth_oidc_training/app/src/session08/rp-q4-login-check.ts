// 練習問題 4 の解答。「ログインできたか」を 2 通りの方法で判断し、結果を比べます。
import { badLoginCheck, fetchMachineTokens, goodLoginCheck } from "./rp-login-check.js";
import { loginHeadless } from "../test-helpers/headless-login.js";

const { tokens, nonce } = await loginHeadless(); // alice が実際にログインした結果
const machine = await fetchMachineTokens(); // 利用者不在の batch-worker のトークン
const machineAccessToken = typeof machine["access_token"] === "string" ? machine["access_token"] : "";
const machineIdToken = typeof machine["id_token"] === "string" ? machine["id_token"] : undefined;

console.log("=== Bad: アクセストークンの検証が通ったら「ログイン済み」とみなす ===");
console.log(`alice のアクセストークン: ${JSON.stringify(await badLoginCheck(tokens.access_token))}`);
console.log(`機械のアクセストークン: loggedIn=${(await badLoginCheck(machineAccessToken)).loggedIn}（誰もログインしていない）`);

console.log("\n=== Good: ID トークンを検証できたら「ログイン済み」とみなす ===");
const alice = await goodLoginCheck({ idToken: tokens.id_token, expectedNonce: nonce });
console.log(`alice: ${alice.loggedIn ? `ログイン済み（${alice.user.username}）` : `未ログイン（${alice.reason}）`}`);
const machineLogin = await goodLoginCheck({ idToken: machineIdToken, expectedNonce: nonce });
console.log(`機械: ${machineLogin.loggedIn ? "ログイン済み" : `未ログイン（${machineLogin.reason}）`}`);

console.log(`\n機械のトークンレスポンスのキー: ${Object.keys(machine).sort().join(", ")}`);

// 2 の結果が危険な理由:
//   本物のアクセストークンなので署名・iss・aud・時刻はすべて正しく、Bad の判定は通ってしまう。
//   その結果、夜間バッチの資格情報を握った者が「ログイン済みの利用者」として扱われる。
// 4 が未ログインと判定できる根拠:
//   Client Credentials では認証イベントが起きていないため、レスポンスに id_token が存在しない。
//   「報告書が無い」ことが、そのまま「誰も本人確認されていない」ことを意味する。
