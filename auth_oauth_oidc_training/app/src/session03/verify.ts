// セッション 3 の自己検証スクリプト。
// 期待値と一致しない場合は非 0 で終了するため、人が出力を読んで判断する必要はありません。
// 実行: docker compose exec app npx tsx src/session03/verify.ts
import { attribute, call, cookieHeader, hasFlag, parseSetCookie } from "./web-app-cookie-tools.js";
import { hashPassword, verifyPassword } from "./web-app-password-store.js";
import { SessionStore, newSessionId } from "./web-app-session-store.js";
import { SESSION_COOKIE, createWebApp } from "./web-app-session-login.js";
import { startServer } from "./web-app-http-tools.js";
import { buildMatrix } from "./web-app-q1-hash-matrix.js";
import { probeTimeouts } from "./web-app-q3-timeout-boundary.js";
import { runFixationScenario } from "./web-app-q4-fixation.js";
import { createThrottledLoginApp } from "./web-app-q5-login-throttle.js";
import { RevocableSessionStore } from "./web-app-q6-revoke-sessions.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

// ---------------------------------------------------------------------------
// 1. パスワードのハッシュ化（Argon2id）
// ---------------------------------------------------------------------------
const stored = await hashPassword("alice-pass");
check("ハッシュ文字列の長さ", stored.length, 97);
check("ハッシュ文字列の先頭", stored.slice(0, 31), "$argon2id$v=19$m=19456,t=2,p=1$");
check("salt の長さ（文字）", (stored.split("$")[4] ?? "").length, 22);
check("hash の長さ（文字）", (stored.split("$")[5] ?? "").length, 43);
check("正しいパスワードの検証", await verifyPassword(stored, "alice-pass"), true);
check("誤ったパスワードの検証", await verifyPassword(stored, "alice-pas"), false);
check("同じパスワードの 2 回のハッシュが異なるか", stored !== (await hashPassword("alice-pass")), true);
check("壊れたハッシュ文字列を渡しても例外にならないか", await verifyPassword("not-a-hash", "alice-pass"), false);

// ---------------------------------------------------------------------------
// 2. セッションストア（ID の作り方と有効期限）
// ---------------------------------------------------------------------------
const ids = new Set<string>();
for (let i = 0; i < 1000; i += 1) {
  ids.add(newSessionId());
}
check("セッション ID の長さ（文字）", newSessionId().length, 43);
check("1000 個のセッション ID がすべて異なるか", ids.size, 1000);

let clock = 1_000_000;
const store = new SessionStore({ idleTimeoutMs: 1000, absoluteTimeoutMs: 5000, now: () => clock });
const anonymous = store.create(null);
check("発行直後は匿名セッションであること", anonymous.record.username, null);
clock += 900;
check("アイドル期限内なら取得できる", store.get(anonymous.id) !== undefined, true);
clock += 900;
check("アクセスするたびアイドル期限が延びる", store.get(anonymous.id) !== undefined, true);
clock += 1500;
check("アイドル期限を超えたら取得できない", store.get(anonymous.id), undefined);

const longLived = store.create("alice");
for (let i = 0; i < 6; i += 1) {
  clock += 900;
  store.get(longLived.id);
}
check("触り続けても絶対期限を超えたら取得できない", store.get(longLived.id), undefined);

const withCart = store.create(null);
withCart.record.cart.push("Clean Architecture");
const rotated = store.regenerate(withCart.id, "alice");
check("再生成でセッション ID が変わるか", rotated.id !== withCart.id, true);
check("再生成後はログイン済みになるか", rotated.record.username, "alice");
check("カートが引き継がれるか", rotated.record.cart, ["Clean Architecture"]);
check("再生成前の古い ID は無効になるか", store.get(withCart.id), undefined);
store.destroy(rotated.id);
check("destroy 後は取得できないか", store.get(rotated.id), undefined);

// ---------------------------------------------------------------------------
// 3. Cookie の発行とログイン・ログアウト
// ---------------------------------------------------------------------------
const web = await createWebApp();

const firstVisit = await call(web, "/cart");
const issued = parseSetCookie(firstVisit.setCookie);
check("GET /cart のステータス", firstVisit.status, 200);
check("発行された Cookie の名前", issued?.name, SESSION_COOKIE);
check("Cookie の値の長さ（文字）", issued?.value.length, 43);
check("HttpOnly が付いているか", issued !== undefined && hasFlag(issued, "HttpOnly"), true);
check("SameSite の値", issued === undefined ? "" : attribute(issued, "SameSite"), "Lax");
check("Path の値", issued === undefined ? "" : attribute(issued, "Path"), "/");
check("学習環境（HTTP）では Secure が付かないこと", issued !== undefined && hasFlag(issued, "Secure"), false);
check("未ログインの /cart のレスポンス", JSON.parse(firstVisit.body), { username: null, cart: [] });

// cookieSecure: true にすると Secure が付く
const secureApp = await createWebApp({ cookieSecure: true });
const secureCookie = parseSetCookie((await call(secureApp, "/cart")).setCookie);
check(
  "cookieSecure: true なら Secure が付くか",
  secureCookie !== undefined && hasFlag(secureCookie, "Secure"),
  true,
);

const beforeLogin = issued?.value ?? "";
const beforeHeader = cookieHeader(SESSION_COOKIE, beforeLogin);
const addToCart = await call(web, "/cart", {
  method: "POST",
  cookie: beforeHeader,
  form: { title: "Clean Architecture" },
});
check("カートに追加した結果", JSON.parse(addToCart.body), { cart: ["Clean Architecture"] });

const login = await call(web, "/login", {
  method: "POST",
  cookie: beforeHeader,
  form: { username: "alice", password: "alice-pass" },
});
const afterLogin = parseSetCookie(login.setCookie)?.value ?? "";
const afterHeader = cookieHeader(SESSION_COOKIE, afterLogin);
check("ログインのステータス", login.status, 200);
check("ログインでセッション ID が再生成されるか", afterLogin !== "" && afterLogin !== beforeLogin, true);
check("ログイン後のレスポンス", JSON.parse(login.body), {
  username: "alice",
  roles: ["customer"],
  cart: ["Clean Architecture"],
});

check("/me（有効な Cookie）のステータス", (await call(web, "/me", { cookie: afterHeader })).status, 200);
check("/me（Cookie なし）のステータス", (await call(web, "/me")).status, 401);
check(
  "/me（1 文字だけ書き換えた Cookie）のステータス",
  (await call(web, "/me", { cookie: cookieHeader(SESSION_COOKIE, `${afterLogin}x`) })).status,
  401,
);
check("/me（再生成前の古い Cookie）のステータス", (await call(web, "/me", { cookie: beforeHeader })).status, 401);

const wrongPassword = await call(web, "/login", {
  method: "POST",
  form: { username: "alice", password: "wrong-pass" },
});
check("誤ったパスワードのステータス", wrongPassword.status, 401);
check("ログイン失敗時に Cookie を発行しないこと", wrongPassword.setCookie, null);
const unknownUser = await call(web, "/login", {
  method: "POST",
  form: { username: "nobody", password: "wrong-pass" },
});
check("存在しない利用者名のステータス", unknownUser.status, 401);
check("存在しない利用者名と誤ったパスワードで応答が同じか", unknownUser.body === wrongPassword.body, true);

const logout = await call(web, "/logout", { method: "POST", cookie: afterHeader });
check("ログアウトのステータス", logout.status, 200);
check("ログアウトで Cookie を空にするか", parseSetCookie(logout.setCookie)?.value, "");
check("ログアウト後の /me のステータス", (await call(web, "/me", { cookie: afterHeader })).status, 401);

// ---------------------------------------------------------------------------
// 4. 本物の HTTP サーバー越しでも同じ挙動になること（Node の HTTP 層を通す確認）
// ---------------------------------------------------------------------------
const server = await startServer(await createWebApp(), 3901);
const overHttp = await server.call("/cart");
const httpCookie = parseSetCookie(overHttp.setCookie);
check("HTTP 越しの GET /cart のステータス", overHttp.status, 200);
check("HTTP 越しでも HttpOnly が付くか", httpCookie !== undefined && hasFlag(httpCookie, "HttpOnly"), true);
const httpHeader = cookieHeader(SESSION_COOKIE, httpCookie?.value ?? "");
const httpLogin = await server.call("/login", {
  method: "POST",
  cookie: httpHeader,
  form: { username: "bob", password: "bob-pass" },
});
check("HTTP 越しのログインのステータス", httpLogin.status, 200);
const httpMe = await server.call("/me", {
  cookie: cookieHeader(SESSION_COOKIE, parseSetCookie(httpLogin.setCookie)?.value ?? ""),
});
check("HTTP 越しの /me のステータス", httpMe.status, 200);
check("HTTP 越しの /me が返すロール", JSON.parse(httpMe.body)["roles"], ["customer", "staff"]);
server.close();

// ---------------------------------------------------------------------------
// 5. 練習問題の解答コード
// ---------------------------------------------------------------------------
const matrix = await buildMatrix();
check("問題 1: 突き合わせの結果", matrix.rows.map((row) => row.verified), [true, false, false, true]);
check("問題 1: 2 人の salt が異なるか", matrix.saltsDiffer, true);
check("問題 1: ハッシュ文字列の長さ", matrix.hashLength, 97);

check("問題 3: 有効期限の境界", probeTimeouts(), {
  atIdleLimit: true,
  justOverIdleLimit: false,
  aliveWhileTouched: true,
  aliveAfterAbsoluteLimit: false,
});

const noRotation = await runFixationScenario(false);
check("問題 4（対策なし）: 被害者のログインは成功する", noRotation.loginStatus, 200);
check("問題 4（対策なし）: セッション ID が変わらない", noRotation.idChanged, false);
check("問題 4（対策なし）: 攻撃者の Cookie で /me が通ってしまう", noRotation.attackerStatus, 200);
const withRotation = await runFixationScenario(true);
check("問題 4（対策あり）: セッション ID が変わる", withRotation.idChanged, true);
check("問題 4（対策あり）: 攻撃者の Cookie は無効になる", withRotation.attackerStatus, 401);

let throttleClock = 0;
const throttled = await createThrottledLoginApp({
  now: () => throttleClock,
  maxAttempts: 5,
  lockMs: 60_000,
});
const attemptStatuses: number[] = [];
for (let attempt = 0; attempt < 5; attempt += 1) {
  const res = await call(throttled, "/login", {
    method: "POST",
    form: { username: "alice", password: "wrong-pass" },
  });
  attemptStatuses.push(res.status);
}
check("問題 5: 5 回までは 401 を返す", attemptStatuses, [401, 401, 401, 401, 401]);
const duringLock = await call(throttled, "/login", {
  method: "POST",
  form: { username: "alice", password: "alice-pass" },
});
check("問題 5: ロック中は正しいパスワードでも 429", duringLock.status, 429);
check("問題 5: ロック中のレスポンス本文", JSON.parse(duringLock.body), { error: "too_many_attempts" });
throttleClock += 60_001;
const afterLock = await call(throttled, "/login", {
  method: "POST",
  form: { username: "alice", password: "alice-pass" },
});
check("問題 5: ロック解除後はログインできる", afterLock.status, 200);
const unknownThrottled = await call(throttled, "/login", {
  method: "POST",
  form: { username: "nobody", password: "wrong-pass" },
});
check("問題 5: 存在しない利用者名も同じ 401 になる", unknownThrottled.status, 401);

const revocable = new RevocableSessionStore();
const alicePc = revocable.create("alice");
const alicePhone = revocable.create("alice");
const aliceTablet = revocable.create("alice");
const bobPc = revocable.create("bob");
check("問題 6: 失効前の alice のセッション数", revocable.countOf("alice"), 3);
check("問題 6: 失効させた件数", revocable.revokeAllOf("alice"), 3);
check(
  "問題 6: alice のセッションがすべて無効になったか",
  revocable.get(alicePc.id) === undefined &&
    revocable.get(alicePhone.id) === undefined &&
    revocable.get(aliceTablet.id) === undefined,
  true,
);
check("問題 6: bob のセッションは残っているか", revocable.get(bobPc.id) !== undefined, true);

console.log(
  failures === 0 ? "\nすべての検証に成功しました。" : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
