// セッション 14 練習問題の解答を検証するスクリプト。
// realm の設定は書き換えません。期待値と一致しなければ非 0 で終了します。
import { loginHeadless } from "../test-helpers/headless-login.js";
import { ISSUER_INTERNAL } from "../session06/bookstore-client.js";
import { matchesRegistration } from "../session12/mobile-redirect.js";
import { createApiApp } from "../session10/api-service-app.js";
import { verifyIgnoringAudience } from "../session10/api-service-audience-lab.js";
import { WILDCARD_REGISTRATION, isAllowedRedirectUri } from "./redirect-uri-guard.js";
import { HardenedPendingLoginStore, consumeWithoutChecks } from "./rp-login-guard.js";
import { auditRedirectUris, auditRegistrations, hijackableUris } from "./rp-q1-redirect-allowlist.js";
import { StateMismatchError, StateOnlyStore, csrfDrill } from "./rp-q2-state-guard.js";
import { auditTokens } from "./api-q3-audience-audit.js";
import { GuardError, IssAwareStore } from "./rp-q4-hardened-store.js";
import { safeRedirectTarget } from "./rp-q5-safe-redirect.js";
import {
  auditLoginDefenses,
  observeCallbackChecks,
  observeLoginDefenses,
  observedToConfig,
  reconcileDefenses,
  toMarkdown,
} from "./rp-q6-defense-audit.js";
import type { LoginConfig, ProbeableStore } from "./rp-q6-defense-audit.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

console.log("=== セッション 14 練習問題の検証 ===\n");

// 問題 1: リダイレクト URI の監査
console.log("問題 1: リダイレクト URI の監査");
const audited = auditRedirectUris([
  "http://localhost:3100/callback",
  "http://localhost:3100/legacy-redirect",
  "http://localhost:3100/oops?next=https://collector.example/log",
]);
check("/callback は横取りリスクなし", audited[0]?.hijackRisk, false);
check("/legacy-redirect は横取りリスクあり", audited[1]?.hijackRisk, true);
check("横取りに使えるのは 2 本", hijackableUris([
  "http://localhost:3100/callback",
  "http://localhost:3100/legacy-redirect",
  "http://localhost:3100/oops?next=https://collector.example/log",
]).length, 2);
const registrations = auditRegistrations(
  ["http://localhost:3100/*", "http://localhost:3100/callback"],
  ["http://localhost:3100/callback", "http://localhost:3100/legacy-redirect"],
);
check("緩い登録値が先に並ぶ", registrations.map((r) => r.registered), [
  "http://localhost:3100/*",
  "http://localhost:3100/callback",
]);
check("ワイルドカード登録は loose", registrations[0]?.loose, true);
check("ワイルドカード登録が余分に許す宛先", registrations[0]?.hijackable, ["http://localhost:3100/legacy-redirect"]);
check("完全一致の登録値は loose でなく余分な宛先も無い", [registrations[1]?.loose, registrations[1]?.hijackable], [false, []]);

// 問題 2: state の照合（CSRF 対策）
console.log("\n問題 2: state の照合");
const own = new URLSearchParams({ state: "my-state", code: "my-code" });
const foreign = new URLSearchParams({ state: "attacker-state", code: "attacker-code" });
check("自分のコールバックは受理・他人のは拒否", csrfDrill(own, foreign), { own: "accepted", foreign: "rejected" });
const store = new StateOnlyStore();
store.remember({ state: "my-state", codeVerifier: "v" });
let q2Reason = "accepted";
try {
  store.consume(foreign);
} catch (err) {
  q2Reason = err instanceof StateMismatchError ? "rejected" : "other";
}
check("覚えのない state は StateMismatchError", q2Reason, "rejected");

// 問題 3: トークン置換の監査
console.log("\n問題 3: トークン置換の監査");
const alice = await loginHeadless();
const strictApp = createApiApp();
const looseApp = createApiApp({ verify: verifyIgnoringAudience });
const rows = await auditTokens(
  [
    { label: "web-app のアクセストークン", token: alice.tokens.access_token },
    { label: "ID トークン", token: alice.tokens.id_token ?? "" },
  ],
  strictApp,
  looseApp,
);
check("アクセストークンは置換にならない", rows[0]?.substituted, false);
check("アクセストークンはどちらも 200", [rows[0]?.strictStatus, rows[0]?.looseStatus], [200, 200]);
check("ID トークンは aud 未検証だと置換が成立", rows[1]?.substituted, true);
check("ID トークンの aud", rows[1]?.audiences, ["web-app"]);

// 問題 4: state・iss・使い捨てをまとめた受け口
console.log("\n問題 4: state・iss・使い捨て");
const okParams = new URLSearchParams({ state: alice.state, code: alice.callbackParams.get("code") ?? "", iss: ISSUER_INTERNAL });
const s1 = new IssAwareStore();
s1.remember({ state: alice.state, codeVerifier: "v", expectedIssuer: ISSUER_INTERNAL });
check("正しい state・iss は受理", typeof s1.consume(okParams).code, "string");
let reusedReason = "";
try {
  s1.consume(okParams);
} catch (err) {
  reusedReason = (err as GuardError).reason;
}
check("同じ state の再処理は callback_replayed", reusedReason, "callback_replayed");
const s2 = new IssAwareStore();
s2.remember({ state: alice.state, codeVerifier: "v", expectedIssuer: ISSUER_INTERNAL });
const wrongIss = new URLSearchParams({ state: alice.state, code: "c", iss: "http://evil.example/realms/evil" });
let issReason = "";
try {
  s2.consume(wrongIss);
} catch (err) {
  issReason = (err as GuardError).reason;
}
check("iss 不一致は issuer_mismatch", issReason, "issuer_mismatch");
const s3 = new IssAwareStore();
s3.remember({ state: "unknown", codeVerifier: "v", expectedIssuer: ISSUER_INTERNAL });
let stateReason = "";
try {
  s3.consume(new URLSearchParams({ state: "different", code: "c", iss: ISSUER_INTERNAL }));
} catch (err) {
  stateReason = (err as GuardError).reason;
}
check("覚えのない state は state_mismatch", stateReason, "state_mismatch");

// 問題 5: 安全な戻り先の判定
console.log("\n問題 5: 安全な戻り先の判定");
check("相対パスは許可", safeRedirectTarget("/me"), "/me");
check("クエリ付き相対パスは許可", safeRedirectTarget("/settings?tab=1"), "/settings?tab=1");
check("ルート単体は許可", safeRedirectTarget("/"), "/");
check("プロトコル相対 URL は拒否", safeRedirectTarget("//evil.example"), null);
check("バックスラッシュ細工は拒否", safeRedirectTarget("/\\evil.example"), null);
check("絶対 URL は拒否（許可リストなし）", safeRedirectTarget("https://evil.example"), null);
check("javascript: は拒否", safeRedirectTarget("javascript:alert(1)"), null);
check("許可リストに載った絶対 URL は許可", safeRedirectTarget("http://localhost:3100/callback", {
  allowlist: ["http://localhost:3100/callback"],
}), "http://localhost:3100/callback");

// 問題 6: 設定表からの点検と、挙動からの点検、その食い違い
console.log("\n問題 6: 5 つの防御の総合監査");
const declared: LoginConfig = {
  codeChallengeMethod: "S256",
  verifiesState: true,
  verifiesIssuer: true,
  redirectMatching: "exact",
  verifiesAudience: true,
};
const secure = auditLoginDefenses(declared);
check("すべて揃っていれば secure", secure.secure, true);
check("欠けている防御なし", secure.missing, []);
const weak = auditLoginDefenses({
  codeChallengeMethod: "plain",
  verifiesState: false,
  verifiesIssuer: false,
  redirectMatching: "wildcard",
  verifiesAudience: true,
});
check("弱い設定は secure でない", weak.secure, false);
check("欠けている 4 つを列挙", weak.missing, ["PKCE(S256)", "state", "iss", "redirect_uri 完全一致"]);
check("Markdown 表は見出し 2 行 + 防御 5 行 + 空行 + 判定", toMarkdown(weak).split("\n").length, 9);

// 挙動からの点検（1）本文の受け口（state ＋ iss）・完全一致の照合・aud を検証する API
const hardened = await observeLoginDefenses({
  makeStore: (): ProbeableStore => {
    const store = new HardenedPendingLoginStore();
    return { remember: (entry) => store.remember(entry), consume: (params) => store.consumeCallback(params) };
  },
  expectedIssuer: ISSUER_INTERNAL,
  matchesRedirect: (uri) => isAllowedRedirectUri(uri),
  api: strictApp,
  idToken: alice.tokens.id_token ?? "",
});
check("正しいコールバックを受理する（測定が成立している）", hardened.acceptsOwnCallback, true);
check("本文の受け口は state と iss を照合している", [hardened.verifiesState, hardened.verifiesIssuer], [true, true]);
check("完全一致の照合関数は exact と推定される", hardened.redirectMatching, "exact");
check("createApiApp() は aud を検証している", hardened.verifiesAudience, true);

// 挙動からの点検（2）state しか見ない受け口・ワイルドカードの照合・aud を見ない API
const looseObserved = await observeLoginDefenses({
  makeStore: (): ProbeableStore => {
    const store = new StateOnlyStore();
    return { remember: (entry) => store.remember(entry), consume: (params) => store.consume(params) };
  },
  expectedIssuer: ISSUER_INTERNAL,
  matchesRedirect: (uri) => matchesRegistration(WILDCARD_REGISTRATION, uri),
  api: looseApp,
  idToken: alice.tokens.id_token ?? "",
});
check("state だけの受け口は iss を見ていない", [looseObserved.verifiesState, looseObserved.verifiesIssuer], [true, false]);
check("ワイルドカードの照合関数は wildcard と推定される", looseObserved.redirectMatching, "wildcard");
check("verifyIgnoringAudience を差した API は aud を見ていない", looseObserved.verifiesAudience, false);

// 挙動からの点検（3）何も照合しない受け口は、どちらのプローブも受理してしまう
const noChecks = observeCallbackChecks(
  () => ({ remember: () => undefined, consume: (params) => consumeWithoutChecks(params) }),
  ISSUER_INTERNAL,
);
check("何も照合しない受け口は state も iss も見ていない", [noChecks.verifiesState, noChecks.verifiesIssuer], [false, false]);

// 設定表と挙動の食い違い（設定はあるのに動いていない）
const gap = reconcileDefenses(declared, looseObserved);
check("設定はあるのに動いていない防御", gap.unimplemented, ["iss", "redirect_uri 完全一致", "aud"]);
check("設定に無いが動いている防御は無い", gap.undocumented, []);
check("食い違いがあれば trustworthy でない", gap.trustworthy, false);
const consistent = reconcileDefenses(declared, hardened);
check("設定と挙動が一致すれば trustworthy", consistent.trustworthy, true);
check("突き合わせの行数は 4（PKCE は挙動から測れない）", consistent.rows.length, 4);

// 別解: 観測値を設定表の形に起こし、設定表の点検と同じ書式で報告する
check("挙動から起こした設定表は secure", auditLoginDefenses(observedToConfig(hardened, "S256")).secure, true);
check(
  "緩い側を起こした設定表は 3 つ欠ける",
  auditLoginDefenses(observedToConfig(looseObserved, "S256")).missing,
  ["iss", "redirect_uri 完全一致", "aud"],
);

console.log(
  failures === 0
    ? "\nセッション 14 練習問題のすべての検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
