// セッション 14 の自己検証スクリプト。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了します（人が出力を読んで判断する必要はありません）。
// realm の設定は一切書き換えません。攻撃は同梱サンドボックスの中の自分のクライアントに対してだけ行います。
import type { JWTPayload } from "jose";
import { decodeJwtPart, loginHeadless } from "../test-helpers/headless-login.js";
import { PendingLoginStore } from "../session06/rp-authorize.js";
import { TokenExchangeError, exchangeCodeForTokens } from "../session06/rp-token-exchange.js";
import { ISSUER_INTERNAL, REDIRECT_URI } from "../session06/bookstore-client.js";
import { createApiApp } from "../session10/api-service-app.js";
import { audiencesOf } from "../session10/api-service-claims.js";
import { verifyIgnoringAudience } from "../session10/api-service-audience-lab.js";
import { compareMatching } from "./redirect-uri-guard.js";
import { createSafeRp, createVulnerableRp } from "./attacker-code-interception.js";
import { HardenedCallbackError, HardenedPendingLoginStore, consumeWithoutChecks } from "./rp-login-guard.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

console.log("=== セッション 14 の検証 ===\n");

// 1. リダイレクト URI: ワイルドカードと完全一致の差
console.log("1. リダイレクト URI の完全一致");
const rows = compareMatching([
  "http://localhost:3100/callback",
  "http://localhost:3100/legacy-redirect",
  "http://localhost:3100/oops?next=https://collector.example/log",
]);
check("/callback はどちらでも通る", rows[0], {
  uri: "http://localhost:3100/callback",
  passesWildcard: true,
  passesExactMatch: true,
});
check("/legacy-redirect はワイルドカードだけ通る", rows[1], {
  uri: "http://localhost:3100/legacy-redirect",
  passesWildcard: true,
  passesExactMatch: false,
});
check("クエリ付きの偽コールバックもワイルドカードは通す", rows[2]?.passesWildcard, true);
check("完全一致は偽コールバックを拒否", rows[2]?.passesExactMatch, false);

// 1b. 照合関数の戻り値だけでなく、認可サーバーが実際にどこへコードを配送するかを測る。
// ワイルドカード登録 http://localhost:3100/* の内側にある /legacy-redirect を redirect_uri にする。
console.log("\n1b. ワイルドカードの内側なら /callback 以外にもコードが配送される（実測）");
const legacyLogin = await loginHeadless({ redirectUri: "http://localhost:3100/legacy-redirect" });
check(
  "/legacy-redirect にも認可コードが発行される",
  (legacyLogin.callbackParams.get("code") ?? "").length > 0,
  true,
);
check("そのコードはトークンにも交換できる", legacyLogin.tokens.access_token.length > 0, true);

// 2. 未登録の redirect_uri には認可サーバー自身が返さない（踏み台にならない）
console.log("\n2. 未登録の redirect_uri は 400（リダイレクトしない）");
let unregisteredRejected = false;
try {
  await loginHeadless({ redirectUri: "https://evil.example/callback" });
} catch {
  unregisteredRejected = true;
}
check("認可サーバーが未登録の宛先を拒否", unregisteredRejected, true);

// 3. オープンリダイレクト: 届いたコードが外部へ漏れる（合成コードで再現）→ 塞ぐ
console.log("\n3. オープンリダイレクトによる横取りと対策");
const leakPath = `/legacy-redirect?next=${encodeURIComponent("https://collector.example/log")}&code=STOLEN-CODE&state=xyz`;
const vulnRes = await createVulnerableRp().request(leakPath);
const leakLocation = vulnRes.headers.get("location") ?? "";
check("Bad: 転送は 302", vulnRes.status, 302);
check("Bad: 転送先が外部ドメイン", new URL(leakLocation).host, "collector.example");
check("Bad: 転送先に code が載って漏れる", new URL(leakLocation).searchParams.get("code"), "STOLEN-CODE");
const safeRes = await createSafeRp().request(leakPath);
check("Good: 外部への転送は 400 で拒否", safeRes.status, 400);
const safeRelative = await createSafeRp().request("/legacy-redirect?next=/me");
check("Good: アプリ内の相対パスは 302 で許す", safeRelative.status, 302);
check("Good: プロトコル相対 URL は拒否", (await createSafeRp().request("/legacy-redirect?next=//evil.example")).status, 400);

// 4. 横取りしたコードは使い捨て（PKCE / 一度きり）
console.log("\n4. 横取りしたコードの再利用は失敗する");
const victim = await loginHeadless();
const oneTimeStore = new PendingLoginStore();
oneTimeStore.remember({ state: victim.state, codeVerifier: victim.codeVerifier });
const stolen = oneTimeStore.consumeCallback(victim.callbackParams);
let reuseError = "";
try {
  await exchangeCodeForTokens({ code: stolen.code, codeVerifier: stolen.codeVerifier, redirectUri: REDIRECT_URI });
} catch (err) {
  if (!(err instanceof TokenExchangeError)) throw err;
  reuseError = err.error;
}
check("再利用は invalid_grant で失敗", reuseError, "invalid_grant");

// 5. state 欠落による CSRF（ログインの取り違え）
console.log("\n5. state の照合（CSRF 対策）");
const foreign = new URLSearchParams({ state: "attacker-state", code: "attacker-code", iss: ISSUER_INTERNAL });
check("Bad: state を見ないと他人のコードを受け入れる", consumeWithoutChecks(foreign).code, "attacker-code");
const stateStore = new HardenedPendingLoginStore();
stateStore.remember({ state: victim.state, codeVerifier: victim.codeVerifier, expectedIssuer: ISSUER_INTERNAL });
let stateReason = "";
try {
  stateStore.consumeCallback(foreign);
} catch (err) {
  stateReason = (err as HardenedCallbackError).reason;
}
check("Good: 覚えのない state は拒否", stateReason, "state_mismatch");

// 6. 混乱した代理（RFC 9207 の iss）
console.log("\n6. iss の照合（混乱した代理の対策）");
check("コールバックに iss が付いてくる", victim.callbackParams.get("iss"), ISSUER_INTERNAL);
const issStore = new HardenedPendingLoginStore();
issStore.remember({ state: victim.state, codeVerifier: victim.codeVerifier, expectedIssuer: ISSUER_INTERNAL });
const legit = issStore.consumeCallback(victim.callbackParams);
check("正しい state と iss は受理される", typeof legit.code === "string" && legit.code.length > 0, true);
const evilAs = new URLSearchParams({ state: victim.state, code: "code-from-evil-as", iss: "http://evil.example/realms/evil" });
// Bad: セッション 6 の受け口は state だけを照合するので、偽の認可サーバーの応答でも受理してしまう
const legacyStore = new PendingLoginStore();
legacyStore.remember({ state: victim.state, codeVerifier: victim.codeVerifier });
check(
  "Bad: state だけの受け口は偽の認可サーバーの応答を受理する",
  legacyStore.consumeCallback(evilAs).code,
  "code-from-evil-as",
);
const issStore2 = new HardenedPendingLoginStore();
issStore2.remember({ state: victim.state, codeVerifier: victim.codeVerifier, expectedIssuer: ISSUER_INTERNAL });
let issReason = "";
try {
  issStore2.consumeCallback(evilAs);
} catch (err) {
  issReason = (err as HardenedCallbackError).reason;
}
check("Good: iss が違う応答は拒否", issReason, "issuer_mismatch");

// 7. トークン置換（aud 未検証）
console.log("\n7. トークン置換（aud の検証）");
const idToken = victim.tokens.id_token ?? "";
check("ID トークンの aud は web-app", audiencesOf(decodeJwtPart<JWTPayload>(idToken, 1)), ["web-app"]);
const strictApi = createApiApp();
const looseApi = createApiApp({ verify: verifyIgnoringAudience });
const auth = (token: string): { headers: Record<string, string> } => ({ headers: { authorization: `Bearer ${token}` } });
const strictRes = await strictApi.request("/api/whoami", auth(idToken));
check("aud を検証する API は ID トークンを 401 で拒否", strictRes.status, 401);
check(
  "拒否のチャレンジ",
  strictRes.headers.get("www-authenticate"),
  'Bearer realm="api-service", error="invalid_token", error_description="The aud claim did not match"',
);
const looseRes = await looseApi.request("/api/whoami", auth(idToken));
check("aud を検証しない API は通してしまう（200）", looseRes.status, 200);
const aliceAccess = victim.tokens.access_token;
const okRes = await strictApi.request("/api/whoami", auth(aliceAccess));
check("本物のアクセストークンは 200 で通る", okRes.status, 200);

console.log(
  failures === 0
    ? "\nセッション 14 のすべての検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
