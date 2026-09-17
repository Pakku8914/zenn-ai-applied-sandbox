import { checkAccess } from "./q8-scope-policy.js";
import type { Facts, Feature, Target } from "./q8-scope-policy.js";

const alice: Facts = { sub: "sub-alice", scopes: ["openid", "orders:read", "orders:write"], realmRoles: ["customer"] };
const aliceAll: Facts = { ...alice, scopes: ["openid", "orders:read:all"] };
const bob: Facts = { sub: "sub-bob", scopes: ["openid", "orders:read:all"], realmRoles: ["customer", "staff"] };
const aliceOrder: Target = { ownerSub: "sub-alice" };
const bobOrder: Target = { ownerSub: "sub-bob" };

const cases: readonly [string, Feature, Facts, Target, number, string][] = [
  ["自分の注文", "自分の注文を見る", alice, aliceOrder, 200, "allow"],
  ["他人の注文", "自分の注文を見る", alice, bobOrder, 403, "forbidden"],
  ["無い注文", "自分の注文を見る", alice, undefined, 404, "not_found"],
  ["全注文（スコープ不足）", "全員の注文を見る", alice, undefined, 403, "insufficient_scope"],
  ["全注文（ロール不足）", "全員の注文を見る", aliceAll, undefined, 403, "forbidden"],
  ["全注文（staff）", "全員の注文を見る", bob, undefined, 200, "allow"],
  ["在庫（スコープ不足）", "在庫を書き換える", bob, undefined, 403, "insufficient_scope"],
];

let failed = 0;
for (const [label, feature, facts, target, status, error] of cases) {
  const verdict = checkAccess(feature, facts, target);
  const actual = verdict.allow ? "allow" : verdict.error;
  const ok = verdict.status === status && actual === error;
  if (!ok) failed += 1;
  console.log(`${ok ? "OK" : "NG"} ${label}: ${verdict.status} ${actual}${verdict.allow ? "" : ` / ${verdict.reason}`}`);
}
if (failed > 0) process.exit(1);
console.log("すべて期待どおりです");
