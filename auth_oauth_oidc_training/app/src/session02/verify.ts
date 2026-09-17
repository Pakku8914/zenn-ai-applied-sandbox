// セッション 2 の自己検証スクリプト。期待値と一致しなければ非 0 で終了します。
// 実行: docker compose exec app npx tsx src/session02/verify.ts
import { decide } from "./api-authz-decide.js";
import type { Action, Order, Subject } from "./api-authz-decide.js";
import { matchedFactors } from "./api-authz-factors.js";
import type { Factor } from "./api-authz-factors.js";

const issuer = process.env["ISSUER_INTERNAL"] ?? "http://keycloak:8080/realms/bookstore";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

// --- 1. 認可サーバーが実在し、認証と認可のためのエンドポイントを公開していること ---
const res = await fetch(`${issuer}/.well-known/openid-configuration`);
check("discovery の HTTP ステータス", res.status, 200);
const doc = (await res.json()) as Record<string, unknown>;
check("issuer", doc["issuer"], issuer);
const requiredKeys = [
  "authorization_endpoint",
  "token_endpoint",
  "userinfo_endpoint",
  "jwks_uri",
  "introspection_endpoint",
  "revocation_endpoint",
  "end_session_endpoint",
];
for (const key of requiredKeys) {
  check(`${key} があるか`, typeof doc[key] === "string", true);
}

// --- 2. 認可の判断（decide）が 4 つの材料どおりに動くこと ---
const alice: Subject = { userId: "alice", roles: ["customer"], attributes: {} };
const bob: Subject = { userId: "bob", roles: ["customer", "staff"], attributes: { storeId: "shinjuku" } };
const aliceSuspended: Subject = { userId: "alice", roles: ["customer"], attributes: { suspended: true } };

const paidOrder: Order = { orderId: "order-1001", ownerId: "alice", storeId: "shinjuku", status: "paid" };
const shippedOrder: Order = { orderId: "order-1002", ownerId: "alice", storeId: "shinjuku", status: "shipped" };
const canceledOrder: Order = { orderId: "order-1003", ownerId: "alice", storeId: "shinjuku", status: "canceled" };
const bobsOrder: Order = { orderId: "order-2001", ownerId: "bob", storeId: "shinjuku", status: "paid" };
const otherStoreOrder: Order = { orderId: "order-9001", ownerId: "alice", storeId: "ueno", status: "canceled" };

type Expectation = {
  readonly label: string;
  readonly subject: Subject;
  readonly action: Action;
  readonly order: Order;
  readonly allow: boolean;
  readonly reason: string;
};

const expectations: readonly Expectation[] = [
  { label: "alice が order-1001 を read", subject: alice, action: "read", order: paidOrder, allow: true, reason: "自分の注文なので読めます" },
  { label: "alice が order-2001 を read", subject: alice, action: "read", order: bobsOrder, allow: false, reason: "自分の注文でも担当店舗の注文でもありません" },
  { label: "bob が order-1001 を read", subject: bob, action: "read", order: paidOrder, allow: true, reason: "担当店舗の注文なので staff として読めます" },
  { label: "bob が order-9001 を read", subject: bob, action: "read", order: otherStoreOrder, allow: false, reason: "自分の注文でも担当店舗の注文でもありません" },
  { label: "alice が order-1001 を cancel", subject: alice, action: "cancel", order: paidOrder, allow: true, reason: "自分の支払い済みの注文なので取り消せます" },
  { label: "alice が order-1002 を cancel", subject: alice, action: "cancel", order: shippedOrder, allow: false, reason: "発送済みの注文は取り消せません" },
  { label: "alice が order-1003 を refund", subject: alice, action: "refund", order: canceledOrder, allow: false, reason: "返金は staff の権限です" },
  { label: "bob が order-1003 を refund", subject: bob, action: "refund", order: canceledOrder, allow: true, reason: "担当店舗の取り消し済みの注文なので返金できます" },
  { label: "alice（利用停止中）が order-1001 を read", subject: aliceSuspended, action: "read", order: paidOrder, allow: false, reason: "利用停止中の利用者です" },
];

for (const e of expectations) {
  check(`decide: ${e.label}`, decide(e.subject, e.action, e.order), { allow: e.allow, reason: e.reason });
}

// --- 3. 練習問題 5 の matchedFactors が、成立した材料だけを固定順で返すこと ---
type FactorCase = {
  readonly label: string;
  readonly subject: Subject;
  readonly order: Order;
  readonly expected: readonly Factor[];
};

const factorCases: readonly FactorCase[] = [
  { label: "alice + order-1001", subject: alice, order: paidOrder, expected: ["本人", "資源"] },
  { label: "bob + order-1001", subject: bob, order: paidOrder, expected: ["役割", "属性", "資源"] },
  { label: "alice + order-1002", subject: alice, order: shippedOrder, expected: ["本人"] },
  { label: "bob + order-9001", subject: bob, order: otherStoreOrder, expected: ["役割"] },
];

for (const c of factorCases) {
  check(`matchedFactors: ${c.label}`, matchedFactors(c.subject, c.order), c.expected);
}

console.log(
  failures === 0
    ? "\nセッション 2 の検証はすべて成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
