// セッション 12 の練習問題（解答例）の自己検証。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了します。
// realm の設定は書き換えません。問題 5 は認可サーバーを呼ばずに、差し替えたリフレッシュ関数で確かめます。
import { RpSessionStore } from "../session09/rp-session-store.js";
import type { RpSession } from "../session09/rp-session-store.js";
import { impossibleTriangle, optionsIfWeDrop, evaluateRequirements, toMarkdown as q1Markdown } from "./bff-q1-storage-report.js";
import { chooseRedirectUri, registrationCheck, scoreOf } from "./bff-q2-redirect-choice.js";
import { WHY_DETECTION_IS_NEEDED, policyRows, settingsFor, toMarkdown as q3Markdown } from "./bff-q3-refresh-policy.js";
import { createLeakyApp, findTokenLeaks, tokenLeakGuard } from "./bff-q4-leak-guard.js";
import type { Leak } from "./bff-q4-leak-guard.js";
import { withRefresh } from "./bff-q5-auto-refresh.js";
import { buildPlan, residualThreats, toMarkdown as q6Markdown } from "./bff-q6-migration-plan.js";
import { classifyRedirectUri } from "./mobile-redirect.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

/** 問題 4・5 で使う、JWT の形をした文字列（本物のトークンではありません） */
const FAKE_JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJhbGljZSJ9.c2lnbmF0dXJl";

console.log("=== セッション 12 の練習問題の検証 ===\n");

// 問題 1: 3 つの要件は同時に満たせない
console.log("問題 1: トークンの置き場所");
check("3 つを同時に満たす置き場所は無い", impossibleTriangle(), []);
check("JS から使うのを諦めれば選べる置き場所", optionsIfWeDrop("usable-from-script"), [
  "httponly-cookie",
  "bff-server-side",
]);
check("XSS で盗まれるのを受け入れるなら", optionsIfWeDrop("not-stolen-by-xss"), [
  "local-storage",
  "session-storage",
]);
check("リロードを諦めても解決しない", optionsIfWeDrop("survives-reload"), []);
const memoryRow = evaluateRequirements().find((row) => row.kind === "memory");
check("メモリ保管が満たせない要件", memoryRow?.unmet, ["survives-reload", "not-stolen-by-xss"]);
check("問題 1 の表の行数（見出し 2 行 ＋ 5 件）", q1Markdown().split("\n").length, 7);

// 問題 2: リダイレクト先を 1 つ選ぶ
console.log("\n問題 2: リダイレクト先の選定");
const choice = chooseRedirectUri([
  "bookstore://callback",
  "http://127.0.0.1:49152/callback",
  "https://app.bookstore.example/oauth/callback",
]);
check("選ばれた宛先", choice.chosen.uri, "https://app.bookstore.example/oauth/callback");
check("選ばれた宛先の種類", choice.chosen.kind, "https-app-link");
check("落選の順序（点が高い順）", choice.rejected.map((item) => item.uri), [
  "http://127.0.0.1:49152/callback",
  "bookstore://callback",
]);
check(
  "落選の理由（最初に差が付いた基準）",
  choice.rejected.map((item) => item.reason.split("（")[0] ?? ""),
  ["OS が宛先の所有関係を検証しない", "OS が宛先の所有関係を検証しない"],
);
check("https リダイレクトの点", scoreOf(classifyRedirectUri("https://app.bookstore.example/oauth/callback")), 14);
check("カスタム URI スキームの点", scoreOf(classifyRedirectUri("bookstore://callback")), 2);
check(
  "ワイルドカード登録では別のパスも通る",
  registrationCheck("http://localhost:3100/*", ["http://localhost:3100/callback", "http://localhost:3100/admin"]),
  [
    { uri: "http://localhost:3100/callback", accepted: true },
    { uri: "http://localhost:3100/admin", accepted: true },
  ],
);
check(
  "完全一致なら 1 文字違えば通らない",
  registrationCheck("bookstore://callback", ["bookstore://callback", "bookstore://callback2"]).map((r) => r.accepted),
  [true, false],
);

// 問題 3: 配置形態ごとの realm 設定
console.log("\n問題 3: リフレッシュトークンの方針");
check("サーバーサイドは既定のまま", settingsFor("server-side").revokeRefreshToken, false);
check("BFF も既定のまま", settingsFor("spa-with-bff").revokeRefreshToken, false);
check("ブラウザに置く SPA はローテーションを有効にする", settingsFor("spa-token-in-browser").revokeRefreshToken, true);
check("再利用は 1 回も許さない", settingsFor("spa-token-in-browser").refreshTokenMaxReuse, 0);
check("端末側に置くならアイドル期限も狭める", settingsFor("mobile-app").ssoSessionIdleTimeout, 900);
check("BFF ならアイドル期限は既定のまま", settingsFor("spa-with-bff").ssoSessionIdleTimeout, 1800);
check("配置形態の行数", policyRows().length, 4);
check("問題 3 の表の行数（見出し 2 行 ＋ 4 件）", q3Markdown().split("\n").length, 6);
check("再利用検知が要る理由は 4 段階", WHY_DETECTION_IS_NEEDED.length, 4);

// 問題 4: トークンの漏れを機械的に見つける
console.log("\n問題 4: 漏れの検査");
const leaked: Leak[] = [];
const guarded = createLeakyApp(FAKE_JWT, tokenLeakGuard((items) => leaked.push(...items)));
const bare = createLeakyApp(FAKE_JWT);

const bareBody = await bare.request("/bff/debug/token");
check("ガードが無ければ本文で漏れる（status）", bareBody.status, 200);
check("漏れの場所（本文）", (await findTokenLeaks(bareBody)).map((leak) => leak.site), ["body"]);
const bareHeader = await bare.request("/bff/debug/header");
check("漏れの場所（ヘッダ）", (await findTokenLeaks(bareHeader)).map((leak) => `${leak.site}:${leak.detail}`), [
  "header:x-access-token",
]);
const bareCookie = await bare.request("/bff/debug/cookie");
check("漏れの場所（Cookie）", (await findTokenLeaks(bareCookie)).map((leak) => `${leak.site}:${leak.detail}`), [
  "set-cookie:at",
]);
const bareOk = await bare.request("/bff/orders");
check("漏れていない応答は検知しない", await findTokenLeaks(bareOk), []);

const guardedBody = await guarded.request("/bff/debug/token");
check("ガードが本文の漏れを止める", guardedBody.status, 500);
check("差し替えた応答", await guardedBody.json(), { error: "token_leak_blocked" });
const guardedHeader = await guarded.request("/bff/debug/header");
check("ガードがヘッダの漏れを止める", guardedHeader.status, 500);
check("差し替えた応答にヘッダは引き継がれない", guardedHeader.headers.get("x-access-token"), null);
const guardedCookie = await guarded.request("/bff/debug/cookie");
check("ガードが Cookie の漏れを止める", guardedCookie.status, 500);
check("差し替えた応答に Set-Cookie は残らない", guardedCookie.headers.getSetCookie(), []);
const guardedOk = await guarded.request("/bff/orders");
check("漏れていない応答はそのまま通す", guardedOk.status, 200);
check("検知した漏れの一覧", leaked.map((leak) => leak.site), ["body", "header", "set-cookie"]);

// 問題 5: 401 のときだけ 1 回リフレッシュする
console.log("\n問題 5: BFF での自動リフレッシュ");
const store = new RpSessionStore();
const newSession = (): RpSession =>
  store.completeLogin(undefined, {
    user: { sub: "sub-alice", username: "alice", name: "Alice Customer" },
    tokens: { accessToken: "at-1", refreshToken: "rt-1", idToken: "id-1", accessTokenExpiresAt: 0 },
  }).session;

const jsonRes = (status: number): Response =>
  new Response(JSON.stringify({ status }), { status, headers: { "content-type": "application/json" } });

// (1) 上流が 200 なら何もしない
const calls1: string[] = [];
const s1 = newSession();
const r1 = await withRefresh(s1, async (token) => {
  calls1.push(token);
  return jsonRes(200);
});
check("200 のときは呼び出しは 1 回", calls1, ["at-1"]);
check("200 のときはリフレッシュしない", r1.refreshed, false);
check("200 のときトークンは変わらない", s1.tokens?.accessToken, "at-1");

// (2) 上流が 401 ならリフレッシュして 1 回だけ再送する
const calls2: string[] = [];
const s2 = newSession();
const r2 = await withRefresh(
  s2,
  async (token) => {
    calls2.push(token);
    return jsonRes(token === "at-2" ? 200 : 401);
  },
  {
    refresh: async () => ({ access_token: "at-2", refresh_token: "rt-2", expires_in: 300 }),
    now: () => 1_000_000,
  },
);
check("401 のあと新しいトークンで再送する", calls2, ["at-1", "at-2"]);
check("再送の結果", r2.response.status, 200);
check("リフレッシュした", r2.refreshed, true);
check("新しいアクセストークンを書き戻した", s2.tokens?.accessToken, "at-2");
check("新しいリフレッシュトークンも書き戻した", s2.tokens?.refreshToken, "rt-2");
check("期限を absolute な時刻に直して保存した", s2.tokens?.accessTokenExpiresAt, 1_300_000);

// (3) 再試行は 1 回まで
const calls3: string[] = [];
const s3 = newSession();
const r3 = await withRefresh(s3, async (token) => {
  calls3.push(token);
  return jsonRes(401);
}, { refresh: async () => ({ access_token: "at-2", expires_in: 300 }) });
check("2 回目も 401 でも再試行しない", calls3.length, 2);
check("2 回目の 401 をそのまま返す", r3.response.status, 401);
check("refresh_token が無い応答では手元の値を使い続ける", s3.tokens?.refreshToken, "rt-1");

// (4) リフレッシュに失敗したらセッションを捨てる
const s4 = newSession();
const r4 = await withRefresh(s4, async () => jsonRes(401), {
  refresh: async () => {
    throw new Error("invalid_grant");
  },
});
check("失敗したら 401 を返す", r4.response.status, 401);
check("失敗を記録している", r4.sessionDropped, true);
check("セッションからトークンを消している", s4.tokens, undefined);

// (5) 403 は取り直しても結果が変わらないのでリフレッシュしない
const calls5: string[] = [];
const s5 = newSession();
const r5 = await withRefresh(s5, async (token) => {
  calls5.push(token);
  return jsonRes(403);
});
check("403 ではリフレッシュしない", r5.refreshed, false);
check("403 では 1 回しか呼ばない", calls5.length, 1);

// 問題 6: 移行計画
console.log("\n問題 6: BFF への移行計画");
check("現状の脅威", residualThreats("local-storage", "spa-token-in-browser"), [
  "xss-token-theft",
  "xss-request-forgery",
  "refresh-token-longevity",
  "session-fixation",
]);
const plan = buildPlan();
check("段階の数", plan.length, 4);
check("段階 2 で消える脅威", plan[1]?.removed, ["refresh-token-longevity"]);
check("段階 3 で消える脅威", plan[2]?.removed, ["session-fixation"]);
check("段階 3 でもトークンの持ち去りは残る", plan[2]?.remaining, ["xss-token-theft", "xss-request-forgery"]);
check("段階 4 で消える脅威", plan[3]?.removed, ["xss-token-theft"]);
check("段階 4 で新しく現れる脅威", plan[3]?.added, ["bff-session-store"]);
check("最後まで残る脅威", plan[3]?.remaining, ["xss-request-forgery", "bff-session-store"]);
check("問題 6 の表の行数（見出し 2 行 ＋ 4 段階）", q6Markdown().split("\n").length, 6);

console.log(
  failures === 0
    ? "\nセッション 12 の練習問題のすべての検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
