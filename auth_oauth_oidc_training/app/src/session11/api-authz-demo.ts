// 章の内容を通しで動かして、目で確かめるためのデモ。
// 実行: docker compose exec app npx tsx src/session11/api-authz-demo.ts
import { decodeJwtPart, loginHeadless } from "../test-helpers/headless-login.js";
import { extractFacts, factsLine } from "./api-authz-claims.js";
import { BookstoreDirectory } from "./api-authz-directory.js";
import { NO_SCOPE_REQUIRED, REQUIRED_SCOPES } from "./api-authz-policy.js";
import { createOrdersApp } from "./api-authz-server.js";

/** ブラウザ役のヘルパー（セッション 6）でログインして、トークンと判断材料を取り出します */
async function signIn(username: string, password: string) {
  const { tokens } = await loginHeadless({ username, password });
  return { token: tokens.access_token, facts: extractFacts(decodeJwtPart(tokens.access_token, 1)) };
}

const alice = await signIn("alice", "alice-pass");
const bob = await signIn("bob", "bob-pass");

console.log("=== 1. 同じログインから取れる 2 つの権限 ===");
console.log(factsLine("alice", alice.facts));
console.log(factsLine("bob", bob.facts));

const directory = new BookstoreDirectory();
console.log(`alice の sub に紐づいた注文: ${directory.linkAccount(alice.facts.sub, "alice")} 件`);
console.log(`bob の sub に紐づいた注文: ${directory.linkAccount(bob.facts.sub, "bob", { storeId: "shinjuku" })} 件`);

console.log("\n=== 2. 同じトークンでも、API の要件次第で結果が変わる ===");
const strict = createOrdersApp(directory, { requiredScopes: REQUIRED_SCOPES });
const today = createOrdersApp(directory, { requiredScopes: NO_SCOPE_REQUIRED });

// [ラベル, どちらの API か, 誰が, トークン, メソッド, パス]
const cases = [
  ["厳しい設定", strict, "alice", alice.token, "GET", "/orders/order-1001"],
  ["移行中の設定", today, "alice", alice.token, "GET", "/orders/order-1001"],
  ["移行中の設定", today, "alice", alice.token, "GET", "/orders/order-2001"],
  ["移行中の設定", today, "bob", bob.token, "GET", "/orders/order-1001"],
  ["移行中の設定", today, "bob", bob.token, "GET", "/orders/order-9001"],
  ["移行中の設定", today, "alice", alice.token, "POST", "/orders/order-1003/refund"],
  ["移行中の設定", today, "bob", bob.token, "POST", "/orders/order-1003/refund"],
] as const;

for (const [label, api, who, token, method, path] of cases) {
  const res = await api.request(path, { method, headers: { authorization: `Bearer ${token}` } });
  const body = (await res.json()) as { error?: string };
  console.log(`${label} / ${who} ${method} ${path} → ${res.status} ${body.error ?? "ok"}`);
}

console.log("\n=== 3. トークンに載った権限は発行時点のスナップショット ===");
console.log(`alice のトークンの寿命: exp - iat = ${alice.facts.expiresAt - alice.facts.issuedAt} 秒`);
console.log("この間はロールを取り上げても、このトークンは通り続けます");
