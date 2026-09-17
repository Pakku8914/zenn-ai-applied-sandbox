// 練習問題 3 の解答。2 種類のトークンを 2 つの宛先として検証し、結果を表にします。
import { API_AUDIENCE, CLIENT_ID } from "./bookstore-oidc.js";
import { verifyWithAudience } from "./rp-verify-id-token.js";
import { loginHeadless } from "../test-helpers/headless-login.js";

const { tokens } = await loginHeadless();
const cases = [
  ["ID トークン", tokens.id_token ?? ""],
  ["アクセストークン", tokens.access_token],
] as const;

console.log("| トークン | 期待する宛先（audience） | 結果 |");
console.log("| :--- | :--- | :--- |");
for (const [label, token] of cases) {
  for (const audience of [CLIENT_ID, API_AUDIENCE]) {
    console.log(`| ${label} | ${audience} | ${await verifyWithAudience(token, audience)} |`);
  }
}

// なぜこの結果になるのか
// 1 行目: ID トークンの aud は web-app。宛名と期待が一致したので通る
// 2 行目: ID トークンの aud は web-app なので、api-service 宛てとしては「自分宛てではない」
// 3 行目: アクセストークンの aud は api-service。web-app 宛てとしては一致しない
// 4 行目: アクセストークンの aud は api-service。宛名と期待が一致したので通る
