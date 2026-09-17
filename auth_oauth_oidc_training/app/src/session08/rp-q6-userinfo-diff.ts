// 練習問題 6 の解答。ID トークン（認証イベントのスナップショット）と
// UserInfo（いまの属性）に何が入っているかを並べて比べます。
import { verifyIdToken } from "./rp-verify-id-token.js";
import { fetchUserInfo } from "./rp-userinfo.js";
import { decodeJwtPart, loginHeadless } from "../test-helpers/headless-login.js";

const { tokens, nonce } = await loginHeadless();
const idToken = tokens.id_token ?? "";

// 先に検証する。検証していないトークンの中身を使って判断しないためです
const identity = await verifyIdToken({ idToken, expectedNonce: nonce });
const idClaims = decodeJwtPart(idToken, 1);

// UserInfo にはアクセストークンを提示します（ID トークンではありません）
const userInfo = await fetchUserInfo(tokens.access_token);

console.log(`UserInfo の HTTP ステータス: ${userInfo.status}`);
console.log(`sub は ID トークンと一致するか: ${userInfo.claims["sub"] === identity.subject}`);

const CLAIMS = [
  "sub",
  "preferred_username",
  "name",
  "email",
  "email_verified",
  "aud",
  "exp",
  "nonce",
  "at_hash",
];
console.log("\n| クレーム | ID トークン | UserInfo |");
console.log("| :--- | :--- | :--- |");
for (const claim of CLAIMS) {
  console.log(`| ${claim} | ${claim in idClaims ? "あり" : "なし"} | ${claim in userInfo.claims ? "あり" : "なし"} |`);
}

const SHARED = ["sub", "preferred_username", "name", "email", "email_verified"];
const same = SHARED.every((claim) => JSON.stringify(idClaims[claim]) === JSON.stringify(userInfo.claims[claim]));
console.log(`\nいま同じ値か: ${same}（属性が更新された直後はここが false になりえます）`);
