// セッション 12 の自己検証スクリプト。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了するため、人が出力を読んで判断する必要はありません。
// realm の設定は一切書き換えません。HTTP は Hono の app.request() で叩くので実ポートも掴みません。
import { parseSetCookie } from "../session03/web-app-cookie-tools.js";
import { BrowserStub } from "../session09/browser-stub.js";
import { ISSUER_INTERNAL, ISSUER_PUBLIC, RP_BASE_URL, getOpenIdConfig } from "../session09/rp-openid-config.js";
import { RpSessionStore, SESSION_COOKIE } from "../session09/rp-session-store.js";
import { createApiApp } from "../session10/api-service-app.js";
import { createBffApp, relayStatus } from "./bff-api-proxy.js";
import { findVerdict, judgeAll } from "./bff-token-storage.js";
import { classifyRedirectUri, isWildcardRegistration, matchesRegistration } from "./mobile-redirect.js";
import {
  ALL_PLACEMENTS,
  ROTATION_SETTINGS,
  refreshPolicyFor,
} from "./public-client-refresh.js";

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

const jsonOf = async <T>(res: Response): Promise<T> => (await res.json()) as T;

console.log("=== セッション 12 の検証 ===\n");

// 1. トークンの置き場所の評価（ブラウザは要らない。すべて判定のロジック）
console.log("1. トークンの置き場所の評価");
check("localStorage は XSS で盗まれる", findVerdict("local-storage").stolenByXss, true);
check("localStorage の危険度", findVerdict("local-storage").risk, "high");
check("sessionStorage も XSS で盗まれる", findVerdict("session-storage").stolenByXss, true);
check("メモリ保管はリロードで消える", findVerdict("memory").lostOnReload, true);
check("メモリ保管でも XSS では読める", findVerdict("memory").stolenByXss, true);
check("HttpOnly Cookie は XSS で読めない", findVerdict("httponly-cookie").stolenByXss, false);
check("HttpOnly Cookie は JS からも使えない", findVerdict("httponly-cookie").usableFromScript, false);
check("HttpOnly Cookie は CSRF 対策が必要", findVerdict("httponly-cookie").needsCsrfDefense, true);
check("BFF のサーバー側保管の危険度", findVerdict("bff-server-side").risk, "low");
check(
  "XSS で盗まれる置き場所",
  judgeAll()
    .filter((v) => v.stolenByXss)
    .map((v) => v.kind),
  ["local-storage", "session-storage", "memory"],
);
check(
  "「XSS で盗まれない」かつ「JS から使える」置き場所は無い",
  judgeAll().filter((v) => !v.stolenByXss && v.usableFromScript).length,
  0,
);

// 2. BFF を組み立てる。api-service への問い合わせ口に app.request を差し込む
console.log("\n2. BFF の組み立てとログイン");
const config = await getOpenIdConfig();
const api = createApiApp();
const store = new RpSessionStore();
const { app } = await createBffApp({
  store,
  config,
  apiFetch: async (path, init) => await api.request(path, init),
});

const loginRes = await app.request("/login");
check("/login の status", loginRes.status, 302);
const first = sessionCookieOf(loginRes);
const browser = new BrowserStub();
const opened = await browser.open(toContainerUrl(loginRes.headers.get("location") ?? ""));
check("認可エンドポイントを開いた結果", opened.kind, "login_form");
const callbackLocation =
  opened.kind === "login_form" ? await browser.submitLogin(opened.formAction, "alice", "alice-pass") : "";
const callbackRes = await app.request(`/callback${new URL(callbackLocation).search}`, {
  headers: { cookie: first.header },
});
check("/callback の status", callbackRes.status, 302);
const authed = sessionCookieOf(callbackRes);
check("ログイン成功でセッション ID が作り直されている", authed.value !== first.value && authed.value.length === 43, true);
check("トークンはサーバー側にある", typeof store.get(authed.value)?.tokens?.accessToken, "string");

// 3. ブラウザは Cookie だけで API の結果を受け取れる
console.log("\n3. /bff/orders（BFF がトークンを付けて代理で呼ぶ）");
const ordersRes = await app.request("/bff/orders", { headers: { cookie: authed.header } });
const orders = await jsonOf<{ subject?: string; orders?: string[] }>(ordersRes);
check("/bff/orders の status", ordersRes.status, 200);
check("注文の一覧", orders.orders, ["order-1001", "order-1002", "order-9001"]);
check("subject はトークンの sub と同じ", orders.subject === store.get(authed.value)?.user?.sub, true);
check("応答に JWT らしい文字列（eyJ）が含まれるか", JSON.stringify(orders).includes("eyJ"), false);
check("キャッシュに載せない", ordersRes.headers.get("cache-control"), "no-store");

const whoamiRes = await app.request("/bff/whoami", { headers: { cookie: authed.header } });
const whoami = await jsonOf<{ client?: string; audiences?: string[]; roles?: string[] }>(whoamiRes);
check("/bff/whoami の status", whoamiRes.status, 200);
check("api-service が見たクライアント", whoami.client, "web-app");
check("api-service が見た宛名", whoami.audiences, ["api-service"]);
check("api-service が見たロール", whoami.roles, ["customer"]);

// 4. 認可の結果はそのまま中継される（BFF は認可を上書きしない）
console.log("\n4. 上流の 401・403 の中継");
const inventoryRes = await app.request("/bff/inventory", { headers: { cookie: authed.header } });
check("alice の /bff/inventory は 403（staff ロールが無い）", inventoryRes.status, 403);
check("403 の error", (await jsonOf<{ error?: string }>(inventoryRes)).error, "forbidden");
const noCookieRes = await app.request("/bff/orders");
check("Cookie が無い /bff/orders は 401", noCookieRes.status, 401);
check("401 の error", (await jsonOf<{ error?: string }>(noCookieRes)).error, "unauthorized");
check("上流の 500 は 502 にまとめる", relayStatus(500), 502);
check("上流の 401 はそのまま 401", relayStatus(401), 401);
check("上流の 200 はそのまま 200", relayStatus(200), 200);

// 5. /me はトークンを返さない（セッション 9 の約束を BFF でも守る）
console.log("\n5. /me");
const meRes = await app.request("/me", { headers: { cookie: authed.header } });
const me = await jsonOf<{ user?: { username?: string }; accessTokenExpiresIn?: number }>(meRes);
check("/me の status", meRes.status, 200);
check("ログインした利用者", me.user?.username, "alice");
check("/me にトークンは入っていない", JSON.stringify(me).includes("eyJ"), false);

// 6. 状態を変える操作は同一オリジンからだけ通す（BFF の代償は CSRF）
console.log("\n6. POST /bff/logout と同一オリジンの検査");
const crossOrigin = await app.request("/bff/logout", {
  method: "POST",
  headers: { cookie: authed.header, origin: "http://attacker.example" },
});
check("他サイトからの POST は 403", crossOrigin.status, 403);
check("403 の error", (await jsonOf<{ error?: string }>(crossOrigin)).error, "cross_origin_request");
check("拒否されたのでセッションは残っている", store.size, 1);
const noOrigin = await app.request("/bff/logout", { method: "POST", headers: { cookie: authed.header } });
check("Origin が無い POST も 403", noOrigin.status, 403);

const logoutRes = await app.request("/bff/logout", {
  method: "POST",
  headers: { cookie: authed.header, origin: RP_BASE_URL },
});
check("同一オリジンからの POST は 200", logoutRes.status, 200);
check("応答", await jsonOf<{ loggedOut?: boolean }>(logoutRes), { loggedOut: true });
check("サーバー側のトークンごと消えている", store.size, 0);
check("ログアウト後の /bff/orders は 401", (await app.request("/bff/orders", { headers: { cookie: authed.header } })).status, 401);

// 7. モバイルのリダイレクト先
console.log("\n7. リダイレクト先の評価");
const custom = classifyRedirectUri("bookstore://callback");
check("カスタム URI スキームの種類", custom.kind, "custom-scheme");
check("カスタム URI スキームは横取りされうる", custom.hijackable, true);
check("カスタム URI スキームは OS が所有を検証しない", custom.ownershipVerified, false);
check("カスタム URI スキームは完全一致で登録できる", custom.exactMatchable, true);
const appLink = classifyRedirectUri("https://app.bookstore.example/oauth/callback");
check("https リダイレクトの種類", appLink.kind, "https-app-link");
check("https リダイレクトは横取りされない", appLink.hijackable, false);
check("https リダイレクトは OS が所有を検証する", appLink.ownershipVerified, true);
const loopback = classifyRedirectUri("http://127.0.0.1:49152/callback");
check("ループバックの種類", loopback.kind, "loopback");
check("ループバックは完全一致で照合できない", loopback.exactMatchable, false);
check("平文 http の種類", classifyRedirectUri("http://app.bookstore.example/callback").kind, "unknown");
check(
  "本書の realm の登録はワイルドカード",
  isWildcardRegistration("http://localhost:3100/*"),
  true,
);
check(
  "ワイルドカードだと /callback 以外も通る",
  matchesRegistration("http://localhost:3100/*", "http://localhost:3100/anything"),
  true,
);
check(
  "完全一致なら 1 文字違えば通らない",
  matchesRegistration("bookstore://callback", "bookstore://callback/"),
  false,
);

// 8. 公開クライアントでのリフレッシュトークンの条件
console.log("\n8. リフレッシュトークンの条件");
check("サーバーサイドはローテーション必須ではない", refreshPolicyFor("server-side").rotationRequired, false);
check("BFF は機密クライアントになれる", refreshPolicyFor("spa-with-bff").confidential, true);
check("BFF はローテーション必須ではない", refreshPolicyFor("spa-with-bff").rotationRequired, false);
check("ブラウザに置く SPA はローテーション必須", refreshPolicyFor("spa-token-in-browser").rotationRequired, true);
check("モバイルは再利用検知まで必須", refreshPolicyFor("mobile-app").reuseDetectionRequired, true);
check(
  "ローテーションが必須な配置",
  ALL_PLACEMENTS.filter((placement) => refreshPolicyFor(placement).rotationRequired),
  ["spa-token-in-browser", "mobile-app"],
);
check("配置形態は 4 つ", ALL_PLACEMENTS.length, 4);
check("ローテーションを有効にする realm 設定", ROTATION_SETTINGS, { revokeRefreshToken: true, refreshTokenMaxReuse: 0 });

console.log(
  failures === 0 ? "\nセッション 12 のすべての検証に成功しました。" : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
