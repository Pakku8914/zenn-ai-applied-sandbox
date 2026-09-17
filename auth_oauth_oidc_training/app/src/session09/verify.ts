// セッション 9 の自己検証スクリプト。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了するため、人が出力を読んで判断する必要はありません。
// realm の設定は一切書き換えません。
import { attribute, hasFlag, parseSetCookie } from "../session03/web-app-cookie-tools.js";
import { decodeJwtPart } from "../test-helpers/headless-login.js";
import { BrowserStub } from "./browser-stub.js";
import { ISSUER_INTERNAL, ISSUER_PUBLIC, REDIRECT_URI, getOpenIdConfig, toBrowserUrl } from "./rp-openid-config.js";
import { RpSessionStore, SESSION_COOKIE } from "./rp-session-store.js";
import { createRpApp } from "./rp-server.js";

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

async function errorOf(res: Response): Promise<string> {
  const body = (await res.json()) as { error?: string };
  return body.error ?? "(error なし)";
}

console.log("=== セッション 9 の検証 ===\n");

// 1. discovery（サーバーからサーバーへの通信なので内部名で取得する）
console.log("1. discovery");
const config = await getOpenIdConfig();
const meta = config.serverMetadata();
check("discovery の issuer", meta.issuer, ISSUER_INTERNAL);
check("end_session_endpoint", meta.end_session_endpoint, `${ISSUER_INTERNAL}/protocol/openid-connect/logout`);
check(
  "ブラウザに渡す認可エンドポイントのホスト",
  new URL(toBrowserUrl(new URL(meta.authorization_endpoint ?? ""))).host,
  "localhost:8080",
);

// 2. /login（認可リクエストの開始）
console.log("\n2. /login（認可リクエストの開始）");
const store = new RpSessionStore();
const app = await createRpApp({ store, config });
const loginRes = await app.request("/login");
check("/login の status", loginRes.status, 302);
const authorizeUrl = new URL(loginRes.headers.get("location") ?? "");
check("転送先のホスト", authorizeUrl.host, "localhost:8080");
check("転送先のパス", authorizeUrl.pathname, "/realms/bookstore/protocol/openid-connect/auth");
check("認可リクエストのパラメータ（並べ替え）", [...authorizeUrl.searchParams.keys()].sort(), [
  "client_id",
  "code_challenge",
  "code_challenge_method",
  "nonce",
  "redirect_uri",
  "response_type",
  "scope",
  "state",
]);
check("response_type", authorizeUrl.searchParams.get("response_type"), "code");
check("code_challenge_method", authorizeUrl.searchParams.get("code_challenge_method"), "S256");
check("scope", authorizeUrl.searchParams.get("scope"), "openid profile email");
check("redirect_uri", authorizeUrl.searchParams.get("redirect_uri"), REDIRECT_URI);

const loginCookie = parseSetCookie(loginRes.headers.get("set-cookie"));
check("セッション Cookie の名前", loginCookie?.name, SESSION_COOKIE);
check("HttpOnly が付いている", loginCookie !== undefined && hasFlag(loginCookie, "HttpOnly"), true);
check("SameSite", loginCookie === undefined ? "(なし)" : attribute(loginCookie, "SameSite"), "Lax");
check("Cookie の値はセッション ID だけ（43 文字）", loginCookie?.value.length === 43, true);
const pending = store.get(loginCookie?.value);
check("この時点では誰かが分かっていない", pending?.user, undefined);
check(
  "URL の state と手元の state が一致している",
  pending?.attempt?.state === authorizeUrl.searchParams.get("state"),
  true,
);

// 3. ブラウザ役がログインする（本物のブラウザがやることを置き換えているだけ）
console.log("\n3. ブラウザ役がログインする");
const browser = new BrowserStub();
const opened = await browser.open(toContainerUrl(authorizeUrl.toString()));
check("認可エンドポイントを開いた結果", opened.kind, "login_form");
const callbackLocation =
  opened.kind === "login_form" ? await browser.submitLogin(opened.formAction, "alice", "alice-pass") : "";
const callbackQuery = new URL(callbackLocation).search;
check("コールバックのクエリ（並べ替え）", [...new URL(callbackLocation).searchParams.keys()].sort(), [
  "code",
  "iss",
  "session_state",
  "state",
]);

// 4. /callback（検証とセッション確立）
console.log("\n4. /callback（検証とセッション確立）");
const first = sessionCookieOf(loginRes);
const callbackRes = await app.request(`/callback${callbackQuery}`, { headers: { cookie: first.header } });
if (callbackRes.status !== 302) {
  console.log(`     応答本文: ${await callbackRes.clone().text()}`);
}
check("/callback の status", callbackRes.status, 302);
check("/callback の転送先", callbackRes.headers.get("location"), "/me");
const authed = sessionCookieOf(callbackRes);
check("ログイン成功でセッション ID が作り直されている", authed.value !== first.value && authed.value.length === 43, true);
check("セッションの数", store.size, 1);
const session = store.get(authed.value);
check("使い終わった state / nonce / code_verifier は残っていない", session?.attempt, undefined);
check("トークンはサーバー側のセッションに入っている", typeof session?.tokens?.accessToken, "string");
check("ID トークンの aud", decodeJwtPart<Record<string, unknown>>(session?.tokens?.idToken ?? "", 1)["aud"], "web-app");
check(
  "アクセストークンの aud",
  decodeJwtPart<Record<string, unknown>>(session?.tokens?.accessToken ?? "", 1)["aud"],
  "api-service",
);

// 5. /me（トークンを見せずに「誰か」を返す）
console.log("\n5. /me");
const meRes = await app.request("/me", { headers: { cookie: authed.header } });
const me = (await meRes.json()) as { user?: { sub?: string; username?: string }; accessTokenExpiresIn?: number };
check("/me の status", meRes.status, 200);
check("ログインした利用者", me.user?.username, "alice");
check("応答にトークンは入っていない", JSON.stringify(me).includes("eyJ"), false);
check("アクセストークンの残りは 300 秒前後", (me.accessTokenExpiresIn ?? 0) > 280, true);
check("sub はサーバー側に保管したものと同じ", me.user?.sub === session?.user?.sub, true);
const oldCookieRes = await app.request("/me", { headers: { cookie: first.header } });
check("ログイン前の（古い）セッション ID では 401", oldCookieRes.status, 401);

// 6. アプリのセッションを消すだけでは足りない（認可サーバーのセッションが残る）
console.log("\n6. アプリのセッションを消すだけでは足りない");
store.destroy(authed.value);
check("アプリのセッションを消すと /me は 401", (await app.request("/me", { headers: { cookie: authed.header } })).status, 401);
const login2 = await app.request("/login");
const second = sessionCookieOf(login2);
const reopened = await browser.open(toContainerUrl(login2.headers.get("location") ?? ""));
check("もう一度ログインを始めたときの認可サーバーの応答", reopened.kind, "redirect");
const silentQuery = reopened.kind === "redirect" ? new URL(reopened.location).search : "";
check("ログイン画面を出さずに認可コードが返る", new URLSearchParams(silentQuery).has("code"), true);
const callback2 = await app.request(`/callback${silentQuery}`, { headers: { cookie: second.header } });
check("画面を出さないままログインが完了してしまう", callback2.status, 302);
const authed2 = sessionCookieOf(callback2);

// 7. RP-initiated logout（アプリと認可サーバーの両方からログアウトする）
console.log("\n7. RP-initiated logout");
const storedIdToken = store.get(authed2.value)?.tokens?.idToken ?? "";
const logoutRes = await app.request("/logout", { headers: { cookie: authed2.header } });
check("/logout の status", logoutRes.status, 302);
const endSessionUrl = new URL(logoutRes.headers.get("location") ?? "");
check("ログアウトの転送先ホスト", endSessionUrl.host, "localhost:8080");
check("ログアウトの転送先パス", endSessionUrl.pathname, "/realms/bookstore/protocol/openid-connect/logout");
check("id_token_hint に手元の ID トークンが載っている", endSessionUrl.searchParams.get("id_token_hint") === storedIdToken, true);
check(
  "post_logout_redirect_uri",
  endSessionUrl.searchParams.get("post_logout_redirect_uri"),
  "http://localhost:3100/",
);
check("セッション Cookie を消している", parseSetCookie(logoutRes.headers.get("set-cookie"))?.value, "");
check("アプリ側のセッションは残っていない", store.size, 0);

const loggedOut = await browser.open(toContainerUrl(endSessionUrl.toString()));
check(
  "認可サーバーのログアウト後の転送先",
  loggedOut.kind === "redirect" ? loggedOut.location : `(${loggedOut.kind})`,
  "http://localhost:3100/",
);
const login3 = await app.request("/login");
const reopened3 = await browser.open(toContainerUrl(login3.headers.get("location") ?? ""));
check("ログアウト後にログインを始めたときの応答", reopened3.kind, "login_form");

// 8. openid-client が弾く異常系（どれもトークンエンドポイントに届く前に落ちる）
console.log("\n8. openid-client が弾く異常系");
const noCookie = await app.request(`/callback?state=x&code=y&iss=${encodeURIComponent(ISSUER_INTERNAL)}`);
check("Cookie が無いコールバック", noCookie.status, 400);
check("Cookie が無いコールバックの error", await errorOf(noCookie), "no_login_in_progress");

const probe = await app.request("/login");
const probeCookie = sessionCookieOf(probe);
const wrongState = await app.request(
  `/callback?state=attacker-state&code=y&iss=${encodeURIComponent(ISSUER_INTERNAL)}`,
  { headers: { cookie: probeCookie.header } },
);
check("state が違うコールバック", wrongState.status, 400);
check("state が違うコールバックの error", await errorOf(wrongState), "login_failed");
check("失敗したログインのセッションは消えている", store.get(probeCookie.value), undefined);

const probe2 = await app.request("/login");
const probe2Cookie = sessionCookieOf(probe2);
const validState = store.get(probe2Cookie.value)?.attempt?.state ?? "";
const wrongIss = await app.request(
  `/callback?state=${encodeURIComponent(validState)}&code=y&iss=${encodeURIComponent("http://evil.example.com/realms/bookstore")}`,
  { headers: { cookie: probe2Cookie.header } },
);
check("iss が違うコールバック（state は正しい）", wrongIss.status, 400);
check("iss が違うコールバックの error", await errorOf(wrongIss), "login_failed");

console.log(
  failures === 0
    ? "\nセッション 9 のすべての検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
