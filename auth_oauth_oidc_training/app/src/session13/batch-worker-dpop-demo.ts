// セッション 13: DPoP を付けたときと付けないときの違いを、自分の目で確かめるデモ。
// 実行: docker compose exec app npx tsx src/session13/batch-worker-dpop-demo.ts
import type { JWTPayload } from "jose";
import { TOKEN_ENDPOINT } from "../session04/bookstore-endpoints.js";
import { createApiApp } from "../session10/api-service-app.js";
import { requestClientCredentials } from "./batch-worker-client.js";
import { createDpopKey } from "./bookstore-dpop.js";
import { confirmationThumbprint, verifyDpopProof } from "./api-service-dpop.js";
import { apiUrl } from "./api-service-dpop-app.js";

const decode = (token: string): JWTPayload =>
  JSON.parse(Buffer.from(token.split(".")[1] ?? "", "base64url").toString()) as JWTPayload;

// 1. DPoP ヘッダを付けない、いつものトークン
const plain = await requestClientCredentials();
console.log(`DPoP なし: token_type=${plain.tokenType} cnf=${JSON.stringify(decode(plain.accessToken)["cnf"])}`);

// 2. DPoP ヘッダを付けたトークン
const key = await createDpopKey();
const bound = await requestClientCredentials({
  dpopProof: await key.createProof({ htm: "POST", htu: TOKEN_ENDPOINT }),
});
const claims = decode(bound.accessToken);
const jkt = confirmationThumbprint(claims);
console.log(`DPoP あり: token_type=${bound.tokenType} cnf=${JSON.stringify(claims["cnf"])}`);
console.log(`cnf.jkt が公開鍵のサムプリントと一致するか: ${jkt === key.thumbprint}`);

// 3. 同じトークン文字列を、鍵を持っている人と持っていない人が使ってみる
const url = apiUrl("/api/summary");
const judge = async (label: string, proof: string): Promise<void> => {
  const result = await verifyDpopProof({
    proof,
    method: "GET",
    url,
    accessToken: bound.accessToken,
    expectedThumbprint: jkt ?? "",
  });
  console.log(`${label}: ${result.ok ? "許可" : `拒否（${result.reason}）`}`);
};

await judge("鍵の持ち主", await key.createProof({ htm: "GET", htu: url, accessToken: bound.accessToken }));
const attacker = await createDpopKey();
await judge(
  "盗んだ人（自分の鍵で proof を作る）",
  await attacker.createProof({ htm: "GET", htu: url, accessToken: bound.accessToken }),
);
await judge(
  "横取りした proof を別の URL に使い回す",
  await key.createProof({ htm: "GET", htu: apiUrl("/api/orders"), accessToken: bound.accessToken }),
);

// 4. cnf を見ないリソースサーバー（セッション 10 の API）に、同じトークンを持ち込む
const bearerApi = createApiApp();
const loose = await bearerApi.request("http://api-service:4100/api/whoami", {
  headers: { authorization: `Bearer ${bound.accessToken}` },
});
console.log(`cnf を見ない API に持ち込む: ${loose.status}`);
