// セッション 15（前半）の結果を通しで見るデモ。
// realm は 1 つも作らず、bookstore realm の discovery を「相手の discovery」に見立てて読むだけです。
// 実行: docker compose exec app npx tsx src/session15/rp-trust-check-demo.ts
import { ISSUER } from "../session04/bookstore-endpoints.js";
import { CLIENT_ID } from "../session06/bookstore-client.js";
import { chooseProtocol } from "./bookstore-saml-oidc.js";
import { checkTrust, missingTrust } from "./bookstore-sso-actors.js";

const discovery = (await (await fetch(`${ISSUER}/.well-known/openid-configuration`)).json()) as Record<
  string,
  unknown
>;

// 1. 相手の realm に自分を登録できた場合。4 材料がそろえば設定に進めます
console.log(`1. 欠けている材料: ${JSON.stringify(missingTrust(checkTrust(discovery, CLIENT_ID)))}`);

// 2. 相手から issuer しか聞けていない場合。どこから手を付けるかが分かります
console.log(
  `2. issuer しか分からないとき: ${JSON.stringify(missingTrust(checkTrust({ issuer: discovery["issuer"] }, undefined)))}`,
);

// 3. 3 つの材料は 1 つの URL から機械的に採れます（4 つ目だけが相手の作業待ちです）
console.log(`3. issuer: ${String(discovery["issuer"])}`);
console.log(`4. jwks_uri: ${String(discovery["jwks_uri"])}`);

// 4. 出るときの設計（連携すると「どこまでログアウトするか」が問題になります）
console.log(
  `5. 出口の申告: end_session_endpoint=${typeof discovery["end_session_endpoint"] === "string"} / backchannel_logout_supported=${JSON.stringify(discovery["backchannel_logout_supported"])}`,
);

// 5. 方式の選択。事実を入れると理由まで返るので、記録にそのまま貼れます
const choices = [
  { name: "6. 大手チェーン", req: { partnerSupports: ["saml2"], hasNativeApp: false, needsApiToken: true, partnerPolicy: "saml2" } },
  { name: "7. 小規模書店", req: { partnerSupports: ["saml2", "oidc"], hasNativeApp: true, needsApiToken: true, partnerPolicy: "none" } },
  { name: "8. 個人経営", req: { partnerSupports: [], hasNativeApp: false, needsApiToken: false, partnerPolicy: "none" } },
] as const;

for (const entry of choices) {
  const choice = chooseProtocol(entry.req);
  console.log(`${entry.name}: ${choice.protocol} / ${choice.reason}`);
}
