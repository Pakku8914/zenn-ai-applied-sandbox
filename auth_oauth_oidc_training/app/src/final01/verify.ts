// 最終プロジェクト final01 の自己検証。要件定義の受け入れ条件（AC-1〜AC-15）を検査項目にしてあります。
// 1 つでも期待値と違えば非 0 で終了するので、人が出力を読んで判断する必要はありません。
// realm の設定は一切書き換えません。HTTP は Hono の app.request() で叩くため実ポートも掴みません。
import type { JWTPayload } from "jose";
import { attribute, hasFlag, parseSetCookie } from "../session03/web-app-cookie-tools.js";
import { RefreshError, refreshAccessToken } from "../session07/rp-refresh.js";
import { BrowserStub } from "../session09/browser-stub.js";
import { ISSUER_INTERNAL, ISSUER_PUBLIC, getOpenIdConfig } from "../session09/rp-openid-config.js";
import { RpSessionStore, SESSION_COOKIE } from "../session09/rp-session-store.js";
import { audiencesOf } from "../session10/api-service-claims.js";
import { findOrder } from "../mid01/mid01-orders.js";
import { decodeJwtPart } from "../test-helpers/headless-login.js";
import { createAuditSink } from "./final01-audit.js";
import { BookstoreAccounts } from "./final01-authz.js";
import { runNightlyBatch } from "./final01-batch-worker.js";
import { attributesOf, inventoryOf, orderView, salesReport } from "./final01-catalog.js";
import { createFinalApiApp } from "./final01-api-service.js";
import { checkAuthorizationUrl, leaksCodeVerifier } from "./final01-login-policy.js";
import { createFinalWebApp } from "./final01-rp.js";
import { RefreshRotation } from "./final01-token-guard.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

/** ブラウザ役はコンテナの中にいるので、ブラウザ向けの URL を内部名に戻してから開く */
const toContainerUrl = (url: string): string =>
  url.replace(new URL(ISSUER_PUBLIC).origin, new URL(ISSUER_INTERNAL).origin);

function sessionCookieOf(res: Response): { header: string; value: string } {
  const value = parseSetCookie(res.headers.get("set-cookie"))?.value ?? "";
  return { header: `${SESSION_COOKIE}=${value}`, value };
}

type OrdersView = {
  username?: string;
  roles?: string[];
  count?: number;
  totalAmount?: number;
  orders?: Array<{ orderId?: string }>;
};
type ErrorView = { error?: string; message?: string };
type InventoryView = { storeId?: string; items?: Array<{ isbn?: string; stock?: number }> };

const jsonOf = async <T>(res: Response): Promise<T> => (await res.json()) as T;
/** 監査ログの中から、ある出来事が記録された行数を数える */
const auditCount = (lines: readonly string[], event: string): number =>
  lines.filter((line) => line.includes(`"event":"${event}"`)).length;

console.log("=== 最終プロジェクト final01（3 者構成の書店）の検証 ===\n");

// 0. 3 者を組み立てる。web-app の問い合わせ口には api-service の app.request を差し込む
const config = await getOpenIdConfig();
const accounts = new BookstoreAccounts();
const audit = createAuditSink();
const rotation = new RefreshRotation();
const api = createFinalApiApp({ accounts, audit });
const store = new RpSessionStore();
const { app: web } = await createFinalWebApp({
  store,
  config,
  audit,
  rotation,
  apiFetch: async (path, init) => await api.request(path, init),
});

// 1. AC-1: 台帳と集計（HTTP に触らない部分）
console.log("1. AC-1 台帳・属性・集計");
const report = salesReport();
check("AC-1 売上合計（取り消し済みを除く）", report.totalAmount, 9600);
check("AC-1 有効な注文の件数", report.orderCount, 3);
check("AC-1 取り消し済みの件数", report.canceledCount, 2);
check("AC-1 店舗別の内訳", report.byStore, [
  { storeId: "shinjuku", amount: 9600, orderCount: 3 },
  { storeId: "ueno", amount: 0, orderCount: 0 },
]);
check("AC-1 bob の担当店舗（トークンではなく台帳から）", attributesOf("bob"), { storeId: "shinjuku" });
check("AC-1 alice には担当店舗が無い", attributesOf("alice"), {});
check("AC-1 shinjuku の在庫", inventoryOf("shinjuku").map((item) => item.isbn), ["978-4-00-000001-0"]);
check("AC-1 担当店舗が決まっていなければ在庫は 0 件", inventoryOf(undefined).length, 0);
const order1001 = findOrder("order-1001");
check(
  "AC-1 応答用の形（台帳の内部表現をそのまま出さない）",
  order1001 === undefined ? "(台帳に無い)" : orderView(order1001),
  {
    orderId: "order-1001",
    title: "やさしい TypeScript 入門",
    amount: 3200,
    status: "paid",
    storeId: "shinjuku",
  },
);

// 2. AC-2: ログインの方針（PKCE 必須・S256 のみ・リダイレクト URI 完全一致）
console.log("\n2. AC-2 ログインの方針");
const sound = new URL(
  "http://localhost:8080/realms/bookstore/protocol/openid-connect/auth" +
    "?response_type=code&client_id=web-app&redirect_uri=http%3A%2F%2Flocalhost%3A3100%2Fcallback" +
    "&scope=openid&state=s-1&nonce=n-1&code_challenge=c-1&code_challenge_method=S256",
);
check("AC-2 方針を満たす URL", checkAuthorizationUrl(sound), undefined);
const plain = new URL(sound);
plain.searchParams.set("code_challenge_method", "plain");
check("AC-2 plain は拒否する", checkAuthorizationUrl(plain), "weak_code_challenge_method");
const noPkce = new URL(sound);
noPkce.searchParams.delete("code_challenge");
check("AC-2 PKCE 無しは拒否する", checkAuthorizationUrl(noPkce), "missing_code_challenge");
const noNonce = new URL(sound);
noNonce.searchParams.delete("nonce");
check("AC-2 nonce 無しは拒否する", checkAuthorizationUrl(noNonce), "missing_nonce");
const legacy = new URL(sound);
// realm のワイルドカード登録（http://localhost:3100/*）の内側でも、完全一致でなければ拒否する
legacy.searchParams.set("redirect_uri", "http://localhost:3100/legacy-redirect");
check("AC-2 登録済みの正確な URI 以外は拒否する", checkAuthorizationUrl(legacy), "redirect_uri_not_allowed");

// 3. AC-3: トークンを持たない呼び出しと、保護されていない経路
console.log("\n3. AC-3 トークン無しの api-service");
const noToken = await api.request("/orders");
check("AC-3 status", noToken.status, 401);
check("AC-3 WWW-Authenticate", noToken.headers.get("www-authenticate"), 'Bearer realm="api-service"');
check("AC-3 集計の経路もトークン無しでは通らない", (await api.request("/reports/daily")).status, 401);
const basic = await api.request("/orders", { headers: { authorization: "Basic YWxpY2U6YWxpY2UtcGFzcw==" } });
check("AC-3 Bearer 以外のスキーム", basic.status, 401);
check("AC-3 /health はトークンが要らない", (await api.request("/health")).status, 200);

// 4. AC-4 / AC-5: alice のログイン
console.log("\n4. AC-4 / AC-5 alice のログイン");
const loginRes = await web.request("/login");
check("/login の status", loginRes.status, 302);
const authorizeUrl = new URL(loginRes.headers.get("location") ?? "http://invalid.example/");
check("AC-4 転送先はブラウザから見える名前", authorizeUrl.host, "localhost:8080");
check("AC-4 実際に組み立てた URL も方針を満たす", checkAuthorizationUrl(authorizeUrl), undefined);
check("AC-4 割符は URL に出ていない", leaksCodeVerifier(authorizeUrl), false);
const loginCookie = parseSetCookie(loginRes.headers.get("set-cookie"));
check("AC-5 Cookie の値はセッション ID だけ（43 文字）", loginCookie?.value.length, 43);
check("AC-5 HttpOnly", loginCookie !== undefined && hasFlag(loginCookie, "HttpOnly"), true);
check("AC-5 SameSite", loginCookie === undefined ? "(なし)" : attribute(loginCookie, "SameSite"), "Lax");
const pending = store.get(loginCookie?.value);
check("AC-4 割符はサーバー側にある", (pending?.attempt?.codeVerifier ?? "").length >= 43, true);
const aliceNonce = pending?.attempt?.nonce ?? "";

const browser = new BrowserStub();
const opened = await browser.open(toContainerUrl(authorizeUrl.toString()));
check("認可エンドポイントを開いた結果", opened.kind, "login_form");
const aliceCallback =
  opened.kind === "login_form" ? await browser.submitLogin(opened.formAction, "alice", "alice-pass") : "";
const startCookie = sessionCookieOf(loginRes);
const callbackRes = await web.request(`/callback${new URL(aliceCallback).search}`, {
  headers: { cookie: startCookie.header },
});
if (callbackRes.status !== 302) {
  console.log(`     応答本文: ${await callbackRes.clone().text()}`);
}
check("/callback の status", callbackRes.status, 302);
const alice = sessionCookieOf(callbackRes);
check("AC-5 ログイン成功でセッション ID を作り直している", alice.value !== startCookie.value, true);
const aliceSession = store.get(alice.value);
check("AC-4 使い終わった state・nonce・割符は残っていない", aliceSession?.attempt, undefined);
const aliceAccess = aliceSession?.tokens?.accessToken ?? "";
const aliceIdToken = aliceSession?.tokens?.idToken ?? "";
check("AC-6 アクセストークンの aud", audiencesOf(decodeJwtPart<JWTPayload>(aliceAccess, 1)), ["api-service"]);
check("AC-6 ID トークンの aud（宛先が違う）", audiencesOf(decodeJwtPart<JWTPayload>(aliceIdToken, 1)), ["web-app"]);
check(
  "AC-4 ID トークンの nonce が預けた値と一致",
  decodeJwtPart<JWTPayload>(aliceIdToken, 1)["nonce"] === aliceNonce,
  true,
);
check("AC-14 ログインが記録されている", auditCount(audit.lines, "login.succeeded"), 1);

// 5. AC-7 / AC-8: customer に見えるもの
console.log("\n5. AC-7 / AC-8 alice（customer）に見えるもの");
const aliceOrdersRes = await web.request("/orders", { headers: { cookie: alice.header } });
check("/orders の status", aliceOrdersRes.status, 200);
const aliceOrders = await jsonOf<OrdersView>(aliceOrdersRes);
check("AC-7 利用者名", aliceOrders.username, "alice");
check("AC-7 ロール", aliceOrders.roles, ["customer"]);
check("AC-7 件数", aliceOrders.count, 4);
check("AC-7 合計金額（取り消し済みは含めない）", aliceOrders.totalAmount, 6000);
check("AC-7 注文 ID", (aliceOrders.orders ?? []).map((order) => order.orderId), [
  "order-1001",
  "order-1002",
  "order-1003",
  "order-9001",
]);
check("AC-5 応答にトークンは混ざっていない", JSON.stringify(aliceOrders).includes("eyJ"), false);
check(
  "AC-8 自分の注文 1 件",
  (await web.request("/orders/order-1001", { headers: { cookie: alice.header } })).status,
  200,
);
const aliceForbidden = await web.request("/orders/order-2001", { headers: { cookie: alice.header } });
check("AC-8 他人の注文", aliceForbidden.status, 403);
check("AC-8 403 の本文（理由を明かさない）", await jsonOf<ErrorView>(aliceForbidden), {
  error: "forbidden",
  message: "この注文を参照する権限がありません",
});
const missing = await web.request("/orders/order-4242", { headers: { cookie: alice.header } });
check("AC-8 存在しない注文", missing.status, 404);
check("AC-8 404 の本文", await jsonOf<ErrorView>(missing), { error: "not_found" });
const aliceInventory = await web.request("/inventory", { headers: { cookie: alice.header } });
check("AC-9 customer は在庫を見られない", aliceInventory.status, 403);
check("AC-9 403 の本文（必要な権限の名前は伝えてよい）", (await jsonOf<ErrorView>(aliceInventory)).message, "在庫の参照には staff ロールが必要です");

// 6. AC-6: 宛先が違うトークン・壊れたトークンは受け付けない
console.log("\n6. AC-6 aud と署名の検証");
const idAsBearer = await api.request("/orders", { headers: { authorization: `Bearer ${aliceIdToken}` } });
check("AC-6 ID トークンを Bearer で送った status", idAsBearer.status, 401);
check(
  "AC-6 ID トークンを Bearer で送った challenge",
  (idAsBearer.headers.get("www-authenticate") ?? "").startsWith(
    'Bearer realm="api-service", error="invalid_token"',
  ),
  true,
);
const parts = aliceAccess.split(".");
const signature = parts[2] ?? "";
const broken = `${parts[0]}.${parts[1]}.${signature.startsWith("A") ? "B" : "A"}${signature.slice(1)}`;
const brokenRes = await api.request("/orders", { headers: { authorization: `Bearer ${broken}` } });
check("AC-6 署名を壊したトークン", brokenRes.status, 401);
check("AC-14 拒否が記録されている", auditCount(audit.lines, "token.rejected") >= 4, true);

// 7. AC-10: ログアウト（アプリ・ブラウザ・認可サーバー・リフレッシュトークン）
console.log("\n7. AC-10 ログアウト");
const aliceRefresh = store.get(alice.value)?.tokens?.refreshToken ?? "";
const logoutRes = await web.request("/logout", { headers: { cookie: alice.header } });
check("AC-10 status", logoutRes.status, 302);
const endSessionUrl = new URL(logoutRes.headers.get("location") ?? "http://invalid.example/");
check("AC-10 転送先のパス", endSessionUrl.pathname, "/realms/bookstore/protocol/openid-connect/logout");
check("AC-10 id_token_hint を渡している", endSessionUrl.searchParams.has("id_token_hint"), true);
check(
  "AC-10 post_logout_redirect_uri",
  endSessionUrl.searchParams.get("post_logout_redirect_uri"),
  "http://localhost:3100/",
);
check("AC-10 Cookie を消している", parseSetCookie(logoutRes.headers.get("set-cookie"))?.value, "");
check("AC-10 サーバー側にトークンを残していない", store.size, 0);
check(
  "AC-10 ログアウト後の /orders",
  (await web.request("/orders", { headers: { cookie: alice.header } })).status,
  401,
);
const logoutLine = audit.lines.filter((line) => line.includes('"event":"logout"')).at(-1) ?? "";
check("AC-10 失効エンドポイントが受け付けた", logoutLine.includes('"revocationStatus":200'), true);
// 失効したリフレッシュトークンでは、もう取り直せない（実測: invalid_grant / Session not active）
let refreshStatus = 0;
try {
  await refreshAccessToken({ refreshToken: aliceRefresh });
} catch (err) {
  refreshStatus = err instanceof RefreshError ? err.status : -1;
}
check("AC-10 失効後のリフレッシュ", refreshStatus, 400);
// 本物のブラウザと同じように、ブラウザ役にも end_session を開かせておく（結果は環境で変わるので記録だけ）
const afterEndSession = await browser.open(toContainerUrl(endSessionUrl.toString()));
console.log(`     （参考）end_session を開いた結果: ${afterEndSession.kind}`);

// 8. AC-11 / AC-9: staff に見えるもの
console.log("\n8. AC-11 / AC-9 bob（staff）に見えるもの");
const bobLogin = await web.request("/login");
const bobStart = sessionCookieOf(bobLogin);
const bobForm = await browser.open(toContainerUrl(bobLogin.headers.get("location") ?? ""));
check("AC-10 ログアウト後はログイン画面が出る", bobForm.kind, "login_form");
const bobCallback =
  bobForm.kind === "login_form" ? await browser.submitLogin(bobForm.formAction, "bob", "bob-pass") : "";
const bobCallbackRes = await web.request(`/callback${new URL(bobCallback).search}`, {
  headers: { cookie: bobStart.header },
});
check("bob の /callback の status", bobCallbackRes.status, 302);
const bob = sessionCookieOf(bobCallbackRes);
const bobOrders = await jsonOf<OrdersView>(await web.request("/orders", { headers: { cookie: bob.header } }));
check("AC-11 利用者名", bobOrders.username, "bob");
check("AC-11 ロール", bobOrders.roles, ["customer", "staff"]);
check("AC-11 件数（自分の注文 ＋ 担当店舗の注文）", bobOrders.count, 4);
check("AC-11 合計金額", bobOrders.totalAmount, 9600);
check("AC-11 注文 ID", (bobOrders.orders ?? []).map((order) => order.orderId), [
  "order-1001",
  "order-1002",
  "order-1003",
  "order-2001",
]);
check(
  "AC-11 担当店舗にある他人の注文は読める",
  (await web.request("/orders/order-1001", { headers: { cookie: bob.header } })).status,
  200,
);
check(
  "AC-11 担当外の店舗の注文は読めない",
  (await web.request("/orders/order-9001", { headers: { cookie: bob.header } })).status,
  403,
);
const bobInventoryRes = await web.request("/inventory", { headers: { cookie: bob.header } });
check("AC-9 staff は在庫を見られる", bobInventoryRes.status, 200);
const bobInventory = await jsonOf<InventoryView>(bobInventoryRes);
check("AC-9 担当店舗", bobInventory.storeId, "shinjuku");
check("AC-9 担当店舗の在庫だけ", (bobInventory.items ?? []).map((item) => item.isbn), ["978-4-00-000001-0"]);
check("AC-9 在庫数", (bobInventory.items ?? [])[0]?.stock, 12);
check("AC-8 sub と利用者の対応表は 2 人分", accounts.size, 2);

// 9. AC-12: リフレッシュのローテーションと再利用の検知
console.log("\n9. AC-12 リフレッシュのローテーション");
const bobAccessBefore = store.get(bob.value)?.tokens?.accessToken ?? "";
const bobRefreshBefore = store.get(bob.value)?.tokens?.refreshToken ?? "";
const expire = (cookieValue: string, refreshToken?: string): void => {
  const session = store.get(cookieValue);
  const tokens = session?.tokens;
  if (session === undefined || tokens === undefined) {
    return;
  }
  // 300 秒待つ代わりに、保管してある期限を過去にして「切れた状態」を作る
  session.tokens = {
    accessToken: tokens.accessToken,
    refreshToken: refreshToken ?? tokens.refreshToken,
    idToken: tokens.idToken,
    accessTokenExpiresAt: Date.now() - 1000,
  };
};
expire(bob.value);
check(
  "AC-12 期限切れでも一覧は取れる",
  (await web.request("/orders", { headers: { cookie: bob.header } })).status,
  200,
);
const bobAccessAfter = store.get(bob.value)?.tokens?.accessToken ?? "";
const bobRefreshAfter = store.get(bob.value)?.tokens?.refreshToken ?? "";
check("AC-12 アクセストークンが入れ替わっている", bobAccessAfter !== "" && bobAccessAfter !== bobAccessBefore, true);
check("AC-12 リフレッシュトークンも入れ替わっている", bobRefreshAfter !== bobRefreshBefore, true);
check("AC-12 使用済みとして 1 本覚えている", rotation.size, 1);
check("AC-14 取り直しが記録されている", auditCount(audit.lines, "refresh.rotated"), 1);
// 盗まれた古いリフレッシュトークンを持ち込まれた状況を作る
expire(bob.value, bobRefreshBefore);
const reuse = await web.request("/orders", { headers: { cookie: bob.header } });
check("AC-12 再利用を検知したら 401", reuse.status, 401);
check("AC-12 401 の本文", (await jsonOf<ErrorView>(reuse)).error, "session_revoked");
check("AC-12 セッションを落としている", store.get(bob.value), undefined);
check("AC-14 再利用の検知が記録されている", auditCount(audit.lines, "refresh.reuse_detected"), 1);

// 10. AC-13: 夜間バッチ（Client Credentials）
console.log("\n10. AC-13 夜間バッチ");
const batch = await runNightlyBatch({ apiFetch: async (path, init) => await api.request(path, init) });
check("AC-13 トークンの取得", batch.tokenStatus, 200);
check("AC-13 リフレッシュトークンは返らない", batch.hasRefreshToken, false);
check("AC-13 レスポンスに refresh_token が無い", batch.tokenKeys.includes("refresh_token"), false);
check("AC-13 集計の取得", batch.reportStatus, 200);
check("AC-13 売上合計", batch.totalAmount, 9600);
check("AC-13 有効な注文の件数", batch.orderCount, 3);
check("AC-13 取り消し済みの件数", batch.canceledCount, 2);
const humanReport = await api.request("/reports/daily", {
  headers: { authorization: `Bearer ${bobAccessAfter}` },
});
check("AC-13 web-app のトークンでは集計を取れない", humanReport.status, 403);

// 11. AC-14: 監査ログに書かないもの
console.log("\n11. AC-14 監査ログ");
check("AC-14 トークンらしい文字列が 1 行も無い", audit.lines.some((line) => line.includes("eyJ")), false);
audit.write({
  event: "logout",
  access_token: "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJhbGljZSJ9.signature",
  detail: "Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJhbGljZSJ9.signature",
});
const masked = audit.lines.at(-1) ?? "";
check("AC-14 名前で落とす（access_token）", masked.includes('"access_token":"<redacted> len='), true);
check("AC-14 名前から漏れても値の形で落とす（detail）", masked.includes('"detail":"<redacted> len='), true);
check("AC-14 落としたあともトークンは残っていない", masked.includes("eyJ"), false);
check("AC-14 拒否の判断が記録されている", auditCount(audit.lines, "authz.denied") >= 3, true);

// 12. AC-15: 認証に関わる応答はキャッシュさせない
console.log("\n12. AC-15 cache-control: no-store");
check("AC-15 api-service の 401", (await api.request("/orders")).headers.get("cache-control"), "no-store");
check("AC-15 api-service の 200", (await api.request("/health")).headers.get("cache-control"), "no-store");
check("AC-15 web-app のトップ", (await web.request("/")).headers.get("cache-control"), "no-store");
check(
  "AC-15 web-app の 401",
  (await web.request("/orders")).headers.get("cache-control"),
  "no-store",
);

console.log(
  failures === 0
    ? "\n最終プロジェクト final01 のすべての受け入れ条件を満たしています。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
