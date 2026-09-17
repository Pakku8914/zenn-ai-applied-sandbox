// セッション 11 の自己検証スクリプト。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了するため、人が出力を読んで判断する必要はありません。
// realm の設定は一切書き換えません（クライアントロールの作成は別スクリプトの担当です）。
import type { Hono } from "hono";
import type { Action } from "../session02/api-authz-decide.js";
import { normalizeScope } from "../session07/rp-scope.js";
import { decodeJwtPart, loginHeadless } from "../test-helpers/headless-login.js";
import { extractFacts } from "./api-authz-claims.js";
import type { TokenFacts } from "./api-authz-claims.js";
import { BookstoreDirectory, UNLINKED } from "./api-authz-directory.js";
import { NO_SCOPE_REQUIRED, REQUIRED_SCOPES, authorize, toSubject } from "./api-authz-policy.js";
import type { AuthzOptions } from "./api-authz-policy.js";
import { createOrdersApp } from "./api-authz-server.js";
import type { AuthzEnv } from "./api-authz-server.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

console.log("=== セッション 11 の検証 ===\n");

// 1. 実測トークンから取り出せる材料
console.log("1. トークンに載っている材料");
const aliceLogin = await loginHeadless();
const bobLogin = await loginHeadless({ username: "bob", password: "bob-pass" });
const alicePayload = decodeJwtPart(aliceLogin.tokens.access_token, 1);
const aliceFacts = extractFacts(alicePayload);
const bobFacts = extractFacts(decodeJwtPart(bobLogin.tokens.access_token, 1));

check("アクセストークンの aud", alicePayload["aud"], "api-service");
check("alice の scope（集合として）", normalizeScope(aliceFacts.scopes.join(" ")), "email openid profile");
check("bob の scope（集合として）", normalizeScope(bobFacts.scopes.join(" ")), "email openid profile");
check("alice の realm ロール", aliceFacts.realmRoles, ["customer"]);
check("bob の realm ロール", bobFacts.realmRoles, ["customer", "staff"]);
check("alice のクライアントロール（まだ作っていない）", aliceFacts.clientRoles, []);
check("bob のクライアントロール（まだ作っていない）", bobFacts.clientRoles, []);
check("スコープに orders:read は入っていない", aliceFacts.scopes.includes("orders:read"), false);
check("トークンの寿命（exp - iat）", aliceFacts.expiresAt - aliceFacts.issuedAt, 300);
check("alice の表示名", aliceFacts.username, "alice");

// 2. 判定そのもの（作ったトークンではなく、手で組んだ材料で全パターンを通す）
console.log("\n2. 判定のパターン");
const logic = new BookstoreDirectory();
check("紐づけ前の注文の持ち主", logic.order("order-1001")?.ownerId, UNLINKED);
check("alice に紐づいた注文の件数", logic.linkAccount("sub-alice", "alice"), 4);
check("bob に紐づいた注文の件数", logic.linkAccount("sub-bob", "bob", { storeId: "shinjuku" }), 1);
check("carol は注文を持っていない", logic.linkAccount("sub-carol", "carol", { storeId: "shinjuku" }), 0);

/** 手で組んだ判断材料。既定では orders:read / orders:write の両方を要求したクライアント */
const facts = (over: Partial<TokenFacts>): TokenFacts => ({
  sub: "sub-unknown",
  username: "unknown",
  scopes: ["openid", "orders:read", "orders:write"],
  realmRoles: ["customer"],
  clientRoles: [],
  issuedAt: 1_000,
  expiresAt: 1_300,
  ...over,
});

const aliceFake = facts({ sub: "sub-alice", username: "alice" });
const bobFake = facts({ sub: "sub-bob", username: "bob", realmRoles: ["customer", "staff"] });
const carolAdmin = facts({ sub: "sub-carol", username: "carol", clientRoles: ["orders-admin"] });
const carolPlain = facts({ sub: "sub-carol", username: "carol" });

/** 判定を 1 つの文字列に落とす（allow / deny:落ちた段） */
function judge(f: TokenFacts, action: Action, orderId: string, options: AuthzOptions = {}): string {
  const order = logic.order(orderId);
  if (order === undefined) return "not_found";
  const result = authorize(f, action, order, { attributes: logic.attributesOf(f.sub), ...options });
  return result.allow ? "allow" : `deny:${result.stage}`;
}

check("alice が自分の注文を読む", judge(aliceFake, "read", "order-1001"), "allow");
check("alice が他人の注文を読む", judge(aliceFake, "read", "order-2001"), "deny:subject");
check("alice が担当外店舗にある自分の注文を読む", judge(aliceFake, "read", "order-9001"), "allow");
check("alice が自分の支払い済み注文を取り消す", judge(aliceFake, "cancel", "order-1001"), "allow");
check("alice が発送済みの注文を取り消す", judge(aliceFake, "cancel", "order-1002"), "deny:subject");
check("alice が返金する", judge(aliceFake, "refund", "order-1003"), "deny:subject");
check("bob が担当店舗の他人の注文を読む", judge(bobFake, "read", "order-1001"), "allow");
check("bob が担当外店舗の注文を読む", judge(bobFake, "read", "order-9001"), "deny:subject");
check("bob が担当店舗の取り消し済み注文を返金する", judge(bobFake, "refund", "order-1003"), "allow");
check("bob が取り消されていない注文を返金する", judge(bobFake, "refund", "order-1001"), "deny:subject");
check("クライアントロール orders-admin があると staff として扱える", judge(carolAdmin, "read", "order-1001"), "allow");
check("クライアントロールが無ければ他人の注文は読めない", judge(carolPlain, "read", "order-1001"), "deny:subject");
check("利用停止中はロールより先に落ちる", judge(aliceFake, "read", "order-1001", { attributes: { suspended: true } }), "deny:subject");

const noScope = facts({ sub: "sub-alice", scopes: ["openid"] });
check("スコープが足りなければ本人でも落ちる", judge(noScope, "read", "order-1001"), "deny:scope");
const readOnly = facts({ sub: "sub-alice", scopes: ["openid", "orders:read"] });
check("読めるが書けないクライアント", judge(readOnly, "cancel", "order-1001"), "deny:scope");
check("スコープを強制しない設定なら通る", judge(noScope, "read", "order-1001", { requiredScopes: NO_SCOPE_REQUIRED }), "allow");

const order1001 = logic.order("order-1001");
if (order1001 === undefined) throw new Error("order-1001 が台帳に見つかりません");
check("足りないスコープの一覧", authorize(readOnly, "cancel", order1001).missing, ["orders:write"]);
check("クライアントロールが realm ロールに翻訳される", toSubject(carolAdmin).roles, ["customer", "staff"]);
check("判定の軸は sub", toSubject(aliceFake).userId, "sub-alice");

// 3. HTTP 越しの振る舞い（本物のトークンを使う）
console.log("\n3. HTTP 越しの振る舞い");
const api = new BookstoreDirectory();
check("alice の sub に紐づいた注文", api.linkAccount(aliceFacts.sub, "alice"), 4);
check("bob の sub に紐づいた注文", api.linkAccount(bobFacts.sub, "bob", { storeId: "shinjuku" }), 1);

const denied: string[] = [];
const app = createOrdersApp(api, {
  requiredScopes: NO_SCOPE_REQUIRED,
  onDeny: (line) => denied.push(line),
});
const strictApp = createOrdersApp(api, { requiredScopes: REQUIRED_SCOPES });

async function callApi(
  target: Hono<AuthzEnv>,
  token: string,
  method: "GET" | "POST",
  path: string,
): Promise<{ status: number; error: string; actor: string; auth: string }> {
  const res = await target.request(path, {
    method,
    headers: token === "" ? {} : { authorization: `Bearer ${token}` },
  });
  const body = (await res.json()) as { error?: string; actor?: string };
  return {
    status: res.status,
    error: body.error ?? "",
    actor: body.actor ?? "",
    auth: res.headers.get("www-authenticate") ?? "",
  };
}

const aliceToken = aliceLogin.tokens.access_token;
const bobToken = bobLogin.tokens.access_token;

const own = await callApi(app, aliceToken, "GET", "/orders/order-1001");
check("alice が自分の注文を GET", { status: own.status, actor: own.actor }, { status: 200, actor: "alice" });
const others = await callApi(app, aliceToken, "GET", "/orders/order-2001");
check("alice が他人の注文を GET", { status: others.status, error: others.error }, { status: 403, error: "forbidden" });
const staffRead = await callApi(app, bobToken, "GET", "/orders/order-1001");
check("bob が担当店舗の注文を GET", { status: staffRead.status, actor: staffRead.actor }, { status: 200, actor: "bob" });
const otherStore = await callApi(app, bobToken, "GET", "/orders/order-9001");
check("bob が担当外店舗の注文を GET", { status: otherStore.status, error: otherStore.error }, { status: 403, error: "forbidden" });
const aliceRefund = await callApi(app, aliceToken, "POST", "/orders/order-1003/refund");
check("alice が返金を POST", { status: aliceRefund.status, error: aliceRefund.error }, { status: 403, error: "forbidden" });
const bobRefund = await callApi(app, bobToken, "POST", "/orders/order-1003/refund");
check("bob が返金を POST", { status: bobRefund.status, actor: bobRefund.actor }, { status: 200, actor: "bob" });
const shipped = await callApi(app, aliceToken, "POST", "/orders/order-1002/cancel");
check("発送済みの注文の取り消しを POST", { status: shipped.status, error: shipped.error }, { status: 403, error: "forbidden" });

check("拒否の記録が残った件数", denied.length, 4);
check("記録はすべて利用者側の判断で落ちたもの", denied.every((line) => line.includes("stage=subject")), true);
check("記録には理由が入っている", denied.every((line) => line.includes("reason=")), true);
check("応答の本文に理由は入っていない", others.error.includes("注文"), false);

const missingOrder = await callApi(app, aliceToken, "GET", "/orders/order-4242");
check("存在しない注文", { status: missingOrder.status, error: missingOrder.error }, { status: 404, error: "not_found" });
const noHeader = await callApi(app, "", "GET", "/orders/order-1001");
check("Authorization ヘッダが無い", { status: noHeader.status, error: noHeader.error }, { status: 401, error: "invalid_request" });
check("401 には WWW-Authenticate が付く", noHeader.auth, 'Bearer realm="api-service"');
const badToken = await callApi(app, "not-a-token", "GET", "/orders/order-1001");
check("検証を通らないトークン", { status: badToken.status, error: badToken.error }, { status: 401, error: "invalid_token" });

// 4. スコープとロールの掛け算（同じトークン・同じ利用者でも、要件が違えば結果が違う）
console.log("\n4. スコープとロールの掛け算");
const strictOwn = await callApi(strictApp, aliceToken, "GET", "/orders/order-1001");
check("orders:read を要求する API に今のトークンで入る", { status: strictOwn.status, error: strictOwn.error }, { status: 403, error: "insufficient_scope" });
check("403 に足りないスコープが示される", strictOwn.auth, 'Bearer error="insufficient_scope", scope="orders:read"');
const strictStaff = await callApi(strictApp, bobToken, "GET", "/orders/order-1001");
check("staff ロールがあっても結果は同じ", { status: strictStaff.status, error: strictStaff.error }, { status: 403, error: "insufficient_scope" });

console.log(
  failures === 0
    ? "\nセッション 11 のすべての検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
