// 手元で最初に動かす確認スクリプト。api-service だけを組み立てて、役割による違いを見ます。
// 使い方: docker compose exec app npx tsx src/final01/final01-check.ts
import { loginHeadless } from "../test-helpers/headless-login.js";
import { createFinalApiApp } from "./final01-api-service.js";

const api = createFinalApiApp();
const bearer = (token: string) => ({ headers: { authorization: `Bearer ${token}` } });

const alice = await loginHeadless();
const orders = await api.request("/orders", bearer(alice.tokens.access_token));
console.log(orders.status, await orders.text());
// 期待: 200 {"owner":"alice","roles":["customer"],"count":4,"totalAmount":6000,...}

const bob = await loginHeadless({ username: "bob", password: "bob-pass" });
const inventory = await api.request("/inventory", bearer(bob.tokens.access_token));
console.log(inventory.status, await inventory.text());
// 期待: 200 {"storeId":"shinjuku","items":[{...,"stock":12,...}]}
