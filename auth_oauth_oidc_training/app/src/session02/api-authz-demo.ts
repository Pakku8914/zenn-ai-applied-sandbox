// セッション 2: decide() が 4 つの材料でどう判断を変えるかを表示します。
// 実行: docker compose exec app npx tsx src/session02/api-authz-demo.ts
import { decide } from "./api-authz-decide.js";
import type { Action, Order, Subject } from "./api-authz-decide.js";

// 認証が終わった状態の利用者。bob は新宿店（shinjuku）の staff です。
const alice: Subject = { userId: "alice", roles: ["customer"], attributes: {} };
const bob: Subject = { userId: "bob", roles: ["customer", "staff"], attributes: { storeId: "shinjuku" } };
const aliceSuspended: Subject = { userId: "alice", roles: ["customer"], attributes: { suspended: true } };

// 資源（注文）。持ち主・店舗・状態のどれも判断材料になります。
const paidOrder: Order = { orderId: "order-1001", ownerId: "alice", storeId: "shinjuku", status: "paid" };
const shippedOrder: Order = { orderId: "order-1002", ownerId: "alice", storeId: "shinjuku", status: "shipped" };
const canceledOrder: Order = { orderId: "order-1003", ownerId: "alice", storeId: "shinjuku", status: "canceled" };
const bobsOrder: Order = { orderId: "order-2001", ownerId: "bob", storeId: "shinjuku", status: "paid" };
const otherStoreOrder: Order = { orderId: "order-9001", ownerId: "alice", storeId: "ueno", status: "canceled" };

/** 1 件の試し。factor は「どの材料が効いたか」を示す読者向けの注記です。 */
type Case = {
  readonly label: string;
  readonly subject: Subject;
  readonly action: Action;
  readonly order: Order;
  readonly factor: string;
};

const cases: readonly Case[] = [
  { label: "alice", subject: alice, action: "read", order: paidOrder, factor: "本人" },
  { label: "alice", subject: alice, action: "read", order: bobsOrder, factor: "本人 + 資源" },
  { label: "bob", subject: bob, action: "read", order: paidOrder, factor: "役割 + 属性 + 資源" },
  { label: "bob", subject: bob, action: "read", order: otherStoreOrder, factor: "属性 + 資源" },
  { label: "alice", subject: alice, action: "cancel", order: paidOrder, factor: "本人 + 資源" },
  { label: "alice", subject: alice, action: "cancel", order: shippedOrder, factor: "資源" },
  { label: "alice", subject: alice, action: "refund", order: canceledOrder, factor: "役割" },
  { label: "bob", subject: bob, action: "refund", order: canceledOrder, factor: "役割 + 属性 + 資源" },
  { label: "alice（利用停止中）", subject: aliceSuspended, action: "read", order: paidOrder, factor: "属性" },
];

console.log("=== 認可の判断は 4 つの材料（本人・役割・属性・資源）で決まる ===");
cases.forEach((c, i) => {
  const decision = decide(c.subject, c.action, c.order);
  const verdict = decision.allow ? "許可" : "不許可";
  console.log(
    `[${i + 1}] ${c.label} が ${c.order.orderId} を ${c.action} → ${verdict}（${decision.reason}）／効いた材料: ${c.factor}`,
  );
});
console.log("\n同じ人でも、資源と状態が変わると答えが変わります。これが認可の判断です。");
