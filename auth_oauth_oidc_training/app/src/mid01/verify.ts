// 中間プロジェクト mid01 の自己検証。要件定義の受け入れ条件（AC-1〜AC-12）を検査項目にしてあります。
// 1 つでも期待値と違えば非 0 で終了するので、人が出力を読んで判断する必要はありません。
// realm の設定は一切書き換えません。HTTP は Hono の app.request() で叩くため実ポートも掴みません。
import type { JWTPayload } from "jose";
import { attribute, hasFlag, parseSetCookie } from "../session03/web-app-cookie-tools.js";
import { verifyOptions } from "../session04/api-service-verify-jwt.js";
import { decodeJwtPart } from "../test-helpers/headless-login.js";
import { BrowserStub } from "../session09/browser-stub.js";
import { ISSUER_INTERNAL, ISSUER_PUBLIC, getOpenIdConfig } from "../session09/rp-openid-config.js";
import { RpSessionStore, SESSION_COOKIE } from "../session09/rp-session-store.js";
import { AccountLinks } from "./mid01-accounts.js";
import { audiencesOf } from "./mid01-api-auth.js";
import { createApiApp } from "./mid01-api-server.js";
import { createWebApp } from "./mid01-web-server.js";

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

/** 応答の Set-Cookie から、次のリクエストで送る Cookie ヘッダとセッション ID を取り出す */
function sessionCookieOf(res: Response): { header: string; value: string } {
  const value = parseSetCookie(res.headers.get("set-cookie"))?.value ?? "";
  return { header: `${SESSION_COOKIE}=${value}`, value };
}

type OrdersView = {
  username?: string;
  count?: number;
  totalAmount?: number;
  orders?: Array<{ orderId?: string; title?: string }>;
};
type ErrorView = { error?: string; reason?: string };
type OrderView = { order?: { orderId?: string; title?: string } };

const jsonOf = async <T>(res: Response): Promise<T> => (await res.json()) as T;

console.log("=== 中間プロジェクト mid01（書店にログインを付ける）の検証 ===\n");

// 0. 2 つのサーバーを組み立てる。web-app からの問い合わせ口に api-service の app.request を差し込む
const config = await getOpenIdConfig();
const links = new AccountLinks();
const api = createApiApp({ links });
const store = new RpSessionStore();
const web = await createWebApp({
  store,
  config,
  // Hono の request() は Response も返しうるので、ApiFetch（Promise<Response>）に合わせる
  apiFetch: async (path, init) => await api.request(path, init),
});

// 1. AC-10: トークンを持たない呼び出しは 401 と WWW-Authenticate で返す
console.log("1. AC-10 トークン無しの api-service");
const noToken = await api.request("/orders");
check("AC-10 status", noToken.status, 401);
check("AC-10 WWW-Authenticate", noToken.headers.get("www-authenticate"), 'Bearer realm="bookstore"');
const basicAuth = await api.request("/orders", {
  headers: { authorization: "Basic YWxpY2U6YWxpY2UtcGFzcw==" },
});
check("AC-10 Bearer 以外の status", basicAuth.status, 401);
check(
  "AC-10 Bearer 以外の challenge",
  basicAuth.headers.get("www-authenticate"),
  'Bearer realm="bookstore", error="invalid_request"',
);
check("AC-10 理由は本文に出さない", await jsonOf<ErrorView>(basicAuth), { error: "unauthorized" });
check("AC-5 api-service が求める aud", verifyOptions.audience, "api-service");

// 2. ログインしていない web-app は注文を見せない
console.log("\n2. ログイン前の web-app");
check("ログイン前の /orders", (await web.request("/orders")).status, 401);
check("ログイン前の /me", (await web.request("/me")).status, 401);

// 3. AC-1 / AC-2 / AC-3 / AC-4: /login が何を URL に出し、何をサーバー側に預けるか
console.log("\n3. AC-1〜AC-4 /login の中身");
const loginRes = await web.request("/login");
check("/login の status", loginRes.status, 302);
const authorizeUrl = new URL(loginRes.headers.get("location") ?? "");
check("転送先のホスト（ブラウザから見える名前）", authorizeUrl.host, "localhost:8080");
check("AC-1 code_challenge がある", authorizeUrl.searchParams.has("code_challenge"), true);
check("AC-1 code_challenge_method", authorizeUrl.searchParams.get("code_challenge_method"), "S256");
check("AC-1 URL に code_verifier は出ていない", authorizeUrl.searchParams.has("code_verifier"), false);
const loginCookie = parseSetCookie(loginRes.headers.get("set-cookie"));
const pending = store.get(loginCookie?.value);
check("AC-1 code_verifier はサーバー側にある", (pending?.attempt?.codeVerifier ?? "").length >= 43, true);
check(
  "AC-2 URL の state と手元の state が一致",
  pending?.attempt?.state === authorizeUrl.searchParams.get("state"),
  true,
);
check(
  "AC-3 URL の nonce と手元の nonce が一致",
  pending?.attempt?.nonce === authorizeUrl.searchParams.get("nonce"),
  true,
);
check("AC-4 Cookie の値はセッション ID だけ（43 文字）", loginCookie?.value.length, 43);
check("AC-4 HttpOnly が付いている", loginCookie !== undefined && hasFlag(loginCookie, "HttpOnly"), true);
check("AC-4 SameSite", loginCookie === undefined ? "(なし)" : attribute(loginCookie, "SameSite"), "Lax");
const aliceNonce = pending?.attempt?.nonce ?? "";

// 4. ブラウザ役が alice としてログインし、web-app がコールバックを検証する
console.log("\n4. alice のログイン（ブラウザ役はセッション 9 の BrowserStub）");
const browser = new BrowserStub();
const opened = await browser.open(toContainerUrl(authorizeUrl.toString()));
check("認可エンドポイントを開いた結果", opened.kind, "login_form");
const callbackLocation =
  opened.kind === "login_form" ? await browser.submitLogin(opened.formAction, "alice", "alice-pass") : "";
const callbackQuery = new URL(callbackLocation).search;
const startCookie = sessionCookieOf(loginRes);
const callbackRes = await web.request(`/callback${callbackQuery}`, {
  headers: { cookie: startCookie.header },
});
if (callbackRes.status !== 302) {
  console.log(`     応答本文: ${await callbackRes.clone().text()}`);
}
check("/callback の status", callbackRes.status, 302);
check("/callback の転送先", callbackRes.headers.get("location"), "/orders");
const authed = sessionCookieOf(callbackRes);
check(
  "AC-4 ログイン成功でセッション ID が作り直されている",
  authed.value !== startCookie.value && authed.value.length === 43,
  true,
);
const session = store.get(authed.value);
check("AC-2/AC-3 使い終わった state・nonce・code_verifier は残っていない", session?.attempt, undefined);
check("AC-4 トークンはサーバー側のセッションにある", typeof session?.tokens?.accessToken, "string");
const accessClaims = decodeJwtPart<JWTPayload>(session?.tokens?.accessToken ?? "", 1);
const idClaims = decodeJwtPart<JWTPayload>(session?.tokens?.idToken ?? "", 1);
check("AC-5 アクセストークンの aud（配列に正規化）", audiencesOf(accessClaims), ["api-service"]);
check("ID トークンの aud（こちらは web-app 宛て）", audiencesOf(idClaims), ["web-app"]);
check("AC-3 ID トークンの nonce が預けた値と一致", idClaims["nonce"] === aliceNonce, true);

// 5. AC-7: alice が見えるのは自分の注文だけ
console.log("\n5. AC-7 alice の注文一覧");
const ordersRes = await web.request("/orders", { headers: { cookie: authed.header } });
check("/orders の status", ordersRes.status, 200);
const ordersView = await jsonOf<OrdersView>(ordersRes);
check("AC-7 ログインした利用者", ordersView.username, "alice");
check("AC-7 件数", ordersView.count, 4);
check("AC-7 合計金額（取り消し済みは含めない）", ordersView.totalAmount, 6000);
check("AC-7 注文 ID の一覧", (ordersView.orders ?? []).map((order) => order.orderId), [
  "order-1001",
  "order-1002",
  "order-1003",
  "order-9001",
]);
check("AC-4 応答にトークンは混ざっていない", JSON.stringify(ordersView).includes("eyJ"), false);
const meRes = await web.request("/me", { headers: { cookie: authed.header } });
check("AC-4 /me の応答にもトークンは無い", (await meRes.clone().text()).includes("eyJ"), false);
check("/me の status", meRes.status, 200);

// 6. AC-8 / AC-9: 他人の注文は 403、無い注文は 404
console.log("\n6. AC-8 / AC-9 1 件ずつ取りに行く");
const own = await web.request("/orders/order-1001", { headers: { cookie: authed.header } });
check("自分の注文の status", own.status, 200);
check("自分の注文の中身", (await jsonOf<OrderView>(own)).order?.orderId, "order-1001");
const ueno = await web.request("/orders/order-9001", { headers: { cookie: authed.header } });
check("担当外店舗にある自分の注文（持ち主なので読める）", ueno.status, 200);
const others = await web.request("/orders/order-2001", { headers: { cookie: authed.header } });
check("AC-8 bob の注文の status", others.status, 403);
check("AC-8 bob の注文の本文", await jsonOf<ErrorView>(others), {
  error: "forbidden",
  reason: "自分の注文でも担当店舗の注文でもありません",
});
const missing = await web.request("/orders/order-4242", { headers: { cookie: authed.header } });
check("AC-9 存在しない注文の status", missing.status, 404);
check("AC-9 存在しない注文の本文", await jsonOf<ErrorView>(missing), { error: "not_found" });

// 7. AC-5: aud が違うトークン・署名が壊れたトークンは api-service が弾く
console.log("\n7. AC-5 api-service の aud と署名の検証");
const idToken = session?.tokens?.idToken ?? "";
const idTokenAsBearer = await api.request("/orders", {
  headers: { authorization: `Bearer ${idToken}` },
});
check("AC-5 ID トークンを Bearer で送った status", idTokenAsBearer.status, 401);
check(
  "AC-5 ID トークンを Bearer で送った challenge",
  idTokenAsBearer.headers.get("www-authenticate"),
  'Bearer realm="bookstore", error="invalid_token"',
);
const accessToken = session?.tokens?.accessToken ?? "";
const parts = accessToken.split(".");
const signature = parts[2] ?? "";
// 署名の先頭 1 文字だけを別の文字に替える（Base64URL として読める形のまま署名を壊す）
const broken = `${parts[0]}.${parts[1]}.${signature.startsWith("A") ? "B" : "A"}${signature.slice(1)}`;
const brokenRes = await api.request("/orders", { headers: { authorization: `Bearer ${broken}` } });
check("AC-5 署名を壊したトークンの status", brokenRes.status, 401);
check(
  "AC-5 署名を壊したトークンの challenge",
  brokenRes.headers.get("www-authenticate"),
  'Bearer realm="bookstore", error="invalid_token"',
);

// 8. AC-12（発展）: 期限切れのアクセストークンはリフレッシュして使い直す
console.log("\n8. AC-12 期限切れのアクセストークンを取り直す");
const beforeRefresh = session?.tokens?.accessToken ?? "";
if (session?.tokens !== undefined) {
  // 300 秒待つ代わりに、保管してある期限を過去にして「切れた状態」を作る
  session.tokens = { ...session.tokens, accessTokenExpiresAt: Date.now() - 1000 };
}
const afterExpiry = await web.request("/orders", { headers: { cookie: authed.header } });
check("AC-12 期限切れでも一覧は取れる", afterExpiry.status, 200);
const afterRefresh = store.get(authed.value)?.tokens?.accessToken ?? "";
check("AC-12 アクセストークンが取り直されている", afterRefresh !== "" && afterRefresh !== beforeRefresh, true);
check(
  "AC-12 取り直したトークンの aud も api-service",
  audiencesOf(decodeJwtPart<JWTPayload>(afterRefresh, 1)),
  ["api-service"],
);

// 9. AC-2: 違う state のコールバックは受け付けない
console.log("\n9. AC-2 state の照合");
const probe = await web.request("/login");
const probeCookie = sessionCookieOf(probe);
const wrongState = await web.request(
  `/callback?state=attacker-state&code=dummy-code&iss=${encodeURIComponent(ISSUER_INTERNAL)}`,
  { headers: { cookie: probeCookie.header } },
);
check("AC-2 state が違うコールバックの status", wrongState.status, 400);
check("AC-2 state が違うコールバックの error", (await jsonOf<ErrorView>(wrongState)).error, "login_failed");
check("AC-2 失敗したログインのセッションは消えている", store.get(probeCookie.value), undefined);
const noCookie = await web.request(
  `/callback?state=x&code=y&iss=${encodeURIComponent(ISSUER_INTERNAL)}`,
);
check("AC-2 Cookie が無いコールバックの status", noCookie.status, 400);
check("AC-2 Cookie が無いコールバックの error", (await jsonOf<ErrorView>(noCookie)).error, "no_login_in_progress");

// 10. AC-3: 期待する nonce を書き換えると、ID トークンの検証で落ちる
console.log("\n10. AC-3 nonce の照合");
const probe2 = await web.request("/login");
const probe2Cookie = sessionCookieOf(probe2);
const reopened = await browser.open(toContainerUrl(probe2.headers.get("location") ?? ""));
// 認可サーバーのセッションが生きているので、ログイン画面は出ずに認可コードが返る
check("2 回目のログイン開始でログイン画面は出ない", reopened.kind, "redirect");
const silentQuery = reopened.kind === "redirect" ? new URL(reopened.location).search : "";
check("認可コードは返っている", new URLSearchParams(silentQuery).has("code"), true);
const probe2Session = store.get(probe2Cookie.value);
if (probe2Session?.attempt !== undefined) {
  // 別のログインの応答を持ち込まれた状況を作る（nonce だけが食い違う）
  probe2Session.attempt = { ...probe2Session.attempt, nonce: "tampered-nonce" };
}
const wrongNonce = await web.request(`/callback${silentQuery}`, {
  headers: { cookie: probe2Cookie.header },
});
check("AC-3 nonce が合わないコールバックの status", wrongNonce.status, 400);
check("AC-3 nonce が合わないコールバックの error", (await jsonOf<ErrorView>(wrongNonce)).error, "login_failed");

// 11. AC-6: ログアウト（アプリと認可サーバーの両方）
console.log("\n11. AC-6 ログアウト");
const storedIdToken = store.get(authed.value)?.tokens?.idToken ?? "";
const logoutRes = await web.request("/logout", { headers: { cookie: authed.header } });
check("AC-6 /logout の status", logoutRes.status, 302);
const endSessionUrl = new URL(logoutRes.headers.get("location") ?? "");
check("AC-6 転送先のパス", endSessionUrl.pathname, "/realms/bookstore/protocol/openid-connect/logout");
check("AC-6 転送先のホスト", endSessionUrl.host, "localhost:8080");
check(
  "AC-6 id_token_hint に手元の ID トークンが載っている",
  endSessionUrl.searchParams.get("id_token_hint") === storedIdToken,
  true,
);
check(
  "AC-6 post_logout_redirect_uri",
  endSessionUrl.searchParams.get("post_logout_redirect_uri"),
  "http://localhost:3100/",
);
check("AC-6 セッション Cookie を消している", parseSetCookie(logoutRes.headers.get("set-cookie"))?.value, "");
check("AC-6 サーバー側にトークンを残していない", store.size, 0);
check(
  "AC-6 ログアウト後の /orders",
  (await web.request("/orders", { headers: { cookie: authed.header } })).status,
  401,
);
const loggedOut = await browser.open(toContainerUrl(endSessionUrl.toString()));
check(
  "AC-6 認可サーバーのログアウト後の戻り先",
  loggedOut.kind === "redirect" ? loggedOut.location : `(${loggedOut.kind})`,
  "http://localhost:3100/",
);

// 12. AC-11: 別の利用者は別の注文だけが見える
console.log("\n12. AC-11 bob でログインし直す");
const bobLogin = await web.request("/login");
const bobCookie = sessionCookieOf(bobLogin);
const bobForm = await browser.open(toContainerUrl(bobLogin.headers.get("location") ?? ""));
check("AC-6 ログアウト後はログイン画面が出る", bobForm.kind, "login_form");
const bobCallback =
  bobForm.kind === "login_form" ? await browser.submitLogin(bobForm.formAction, "bob", "bob-pass") : "";
const bobCallbackRes = await web.request(`/callback${new URL(bobCallback).search}`, {
  headers: { cookie: bobCookie.header },
});
check("bob の /callback の status", bobCallbackRes.status, 302);
const bobAuthed = sessionCookieOf(bobCallbackRes);
const bobOrdersRes = await web.request("/orders", { headers: { cookie: bobAuthed.header } });
const bobOrders = await jsonOf<OrdersView>(bobOrdersRes);
check("AC-11 bob の利用者名", bobOrders.username, "bob");
check("AC-11 bob に見える件数", bobOrders.count, 1);
check("AC-11 bob に見える注文", (bobOrders.orders ?? []).map((order) => order.orderId), ["order-2001"]);
check("AC-11 bob の合計金額", bobOrders.totalAmount, 3600);
// bob は staff ロールを持っていますが、このプロジェクトではロールを判断に使わないので他人の注文は読めません
const bobTriesAlice = await web.request("/orders/order-1001", { headers: { cookie: bobAuthed.header } });
check("AC-11 bob が alice の注文を取ると 403", bobTriesAlice.status, 403);
check("AC-11 sub と利用者の対応表は 2 人分", links.size, 2);

// 13. AC-13: 認証に関わる応答はキャッシュさせない
console.log("\n13. AC-13 cache-control: no-store");
const cacheProbe = await api.request("/orders");
check("AC-13 api-service の 401 応答", cacheProbe.headers.get("cache-control"), "no-store");
const webProbe = await web.request("/");
check("AC-13 web-app のトップ", webProbe.headers.get("cache-control"), "no-store");

console.log(
  failures === 0
    ? "\n中間プロジェクト mid01 のすべての受け入れ条件を満たしています。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
