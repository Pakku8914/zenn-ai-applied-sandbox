// セッション 14: 4 つの攻撃と対策を通しで動かすデモ。
// 対象は同梱サンドボックスの中の自分のクライアント（web-app / api-service）だけです。
// 実行: docker compose exec app npx tsx src/session14/demo-attacks.ts
import type { JWTPayload } from "jose";
import { decodeJwtPart, loginHeadless } from "../test-helpers/headless-login.js";
import { PendingLoginStore } from "../session06/rp-authorize.js";
import { TokenExchangeError, exchangeCodeForTokens } from "../session06/rp-token-exchange.js";
import { ISSUER_INTERNAL } from "../session06/bookstore-client.js";
import { matchesRegistration } from "../session12/mobile-redirect.js";
import { createApiApp } from "../session10/api-service-app.js";
import { audiencesOf } from "../session10/api-service-claims.js";
import { verifyIgnoringAudience } from "../session10/api-service-audience-lab.js";
import { WILDCARD_REGISTRATION, isAllowedRedirectUri } from "./redirect-uri-guard.js";
import { createSafeRp, createVulnerableRp } from "./attacker-code-interception.js";
import { HardenedCallbackError, HardenedPendingLoginStore, consumeWithoutChecks } from "./rp-login-guard.js";

// ── 攻撃1: リダイレクト URI の完全一致とオープンリダイレクト ───────────────
console.log("=== 攻撃1: リダイレクト URI の完全一致とオープンリダイレクト ===");
const badUri = "http://localhost:3100/legacy-redirect";
console.log(`ワイルドカード登録は ${badUri} を通す: ${matchesRegistration(WILDCARD_REGISTRATION, badUri)}`);
console.log(`完全一致の許可リストは ${badUri} を通す: ${isAllowedRedirectUri(badUri)}`);
console.log(`完全一致の許可リストは /callback を通す: ${isAllowedRedirectUri("http://localhost:3100/callback")}`);

// 未登録の redirect_uri には認可サーバー自身が返さない（＝踏み台にならない）
try {
  await loginHeadless({ redirectUri: "https://evil.example/callback" });
  console.log("未登録の redirect_uri: 通ってしまった（想定外）");
} catch {
  console.log("未登録の redirect_uri: 認可サーバーが拒否（リダイレクトしない）");
}

// オープンリダイレクトがあると、届いたコードが外部へ漏れる（合成コードで再現）
const leakPath = `/legacy-redirect?next=${encodeURIComponent("https://collector.example/log")}&code=STOLEN-CODE&state=xyz`;
const vulnRes = await createVulnerableRp().request(leakPath);
console.log(`Bad な RP の転送先: ${vulnRes.headers.get("location")}`);
const safeRes = await createSafeRp().request(leakPath);
console.log(`Good な RP の応答: HTTP ${safeRes.status}`);

// ── 攻撃1の最後の砦: 横取りしたコードは使い捨て（PKCE / 一度きり）───────────
console.log("\n=== 攻撃1の最後の砦: 横取りしたコードは使い捨て ===");
const victim = await loginHeadless();
const store = new PendingLoginStore();
store.remember({ state: victim.state, codeVerifier: victim.codeVerifier });
const stolen = store.consumeCallback(victim.callbackParams);
try {
  await exchangeCodeForTokens({ code: stolen.code, codeVerifier: stolen.codeVerifier });
  console.log("横取りしたコードの再利用: 成功してしまった（想定外）");
} catch (err) {
  if (!(err instanceof TokenExchangeError)) throw err;
  console.log(`横取りしたコードの再利用: HTTP ${err.status} ${err.error} / ${err.errorDescription}`);
}

// ── 攻撃2: state 欠落による CSRF（ログインの取り違え）─────────────────────
console.log("\n=== 攻撃2: state 欠落による CSRF（ログインの取り違え）===");
const foreign = new URLSearchParams({ state: "attacker-state", code: "attacker-code", iss: ISSUER_INTERNAL });
console.log(`Bad（state を見ない）: 他人のコード「${consumeWithoutChecks(foreign).code}」を受け入れてしまう`);
const guarded = new HardenedPendingLoginStore();
guarded.remember({ state: victim.state, codeVerifier: victim.codeVerifier, expectedIssuer: ISSUER_INTERNAL });
try {
  guarded.consumeCallback(foreign);
  console.log("Good: 受け入れてしまった（想定外）");
} catch (err) {
  console.log(`Good（state を照合）: 拒否 → ${(err as HardenedCallbackError).reason}`);
}

// ── 攻撃3: 混乱した代理（RFC 9207 の iss）─────────────────────────────────
console.log("\n=== 攻撃3: 混乱した代理（RFC 9207 の iss）===");
console.log(`コールバックに付いてくる iss: ${victim.callbackParams.get("iss")}`);
const evilAs = new URLSearchParams({ state: victim.state, code: "code-from-evil-as", iss: "http://evil.example/realms/evil" });
const guarded2 = new HardenedPendingLoginStore();
guarded2.remember({ state: victim.state, codeVerifier: victim.codeVerifier, expectedIssuer: ISSUER_INTERNAL });
try {
  guarded2.consumeCallback(evilAs);
  console.log("iss を偽った応答: 受け入れてしまった（想定外）");
} catch (err) {
  console.log(`iss を偽った応答: 拒否 → ${(err as HardenedCallbackError).reason}`);
}

// ── 攻撃4: トークン置換（aud 未検証）─────────────────────────────────────
console.log("\n=== 攻撃4: トークン置換（aud 未検証）===");
const idToken = victim.tokens.id_token ?? "";
console.log(`ID トークンの aud: ${audiencesOf(decodeJwtPart<JWTPayload>(idToken, 1)).join(", ")}`);
const strictApi = createApiApp();
const looseApi = createApiApp({ verify: verifyIgnoringAudience });
const strictRes = await strictApi.request("/api/whoami", { headers: { authorization: `Bearer ${idToken}` } });
const looseRes = await looseApi.request("/api/whoami", { headers: { authorization: `Bearer ${idToken}` } });
console.log(`aud を検証する API: HTTP ${strictRes.status}`);
console.log(`aud を検証しない API: HTTP ${looseRes.status}（通ってしまう）`);
