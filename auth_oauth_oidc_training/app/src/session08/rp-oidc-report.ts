// ID トークンとアクセストークンの違いを、実物を並べて確かめるデモ。
// ブラウザの操作だけを検証用ヘルパーに肩代わりさせ、それ以外は自分の実装を使います。
import { badLoginCheck, fetchMachineTokens, goodLoginCheck } from "./rp-login-check.js";
import { fetchUserInfo } from "./rp-userinfo.js";
import { verifyIdToken } from "./rp-verify-id-token.js";
import { decodeJwtPart, loginHeadless } from "../test-helpers/headless-login.js";

const { tokens, nonce } = await loginHeadless(); // 既定は alice
const idToken = tokens.id_token ?? "";
const idNames = Object.keys(decodeJwtPart(idToken, 1)).sort();
const accessNames = Object.keys(decodeJwtPart(tokens.access_token, 1)).sort();

console.log("=== 1. 2 つのトークンのクレームを比べる ===");
console.log(`クレーム数: ID トークン ${idNames.length} / アクセストークン ${accessNames.length}`);
console.log(`ID トークンだけにある: ${idNames.filter((c) => !accessNames.includes(c)).join(", ")}`);
console.log(`アクセストークンだけにある: ${accessNames.filter((c) => !idNames.includes(c)).join(", ")}`);

console.log("\n=== 2. ログイン判定 ===");
const machine = await fetchMachineTokens();
const machineToken = typeof machine["access_token"] === "string" ? machine["access_token"] : "";
console.log(`Bad  alice のアクセストークン: ${JSON.stringify(await badLoginCheck(tokens.access_token))}`);
console.log(`Bad  機械のアクセストークン: loggedIn=${(await badLoginCheck(machineToken)).loggedIn}`);
console.log(`機械のトークンレスポンスに id_token はあるか: ${"id_token" in machine}`);
const alice = await goodLoginCheck({ idToken, expectedNonce: nonce });
console.log(`Good alice: ${alice.loggedIn ? `ログイン済み（${alice.user.username}）` : alice.reason}`);
const machineLogin = await goodLoginCheck({ idToken: undefined, expectedNonce: nonce });
console.log(`Good 機械: ${machineLogin.loggedIn ? "ログイン済み" : `未ログイン（${machineLogin.reason}）`}`);

console.log("\n=== 3. UserInfo と ID トークン ===");
const identity = await verifyIdToken({ idToken, expectedNonce: nonce });
const userInfo = await fetchUserInfo(tokens.access_token);
console.log(`UserInfo: HTTP ${userInfo.status} / sub は一致するか ${userInfo.claims["sub"] === identity.subject}`);
console.log(`UserInfo に exp / nonce はあるか: ${"exp" in userInfo.claims} / ${"nonce" in userInfo.claims}`);
