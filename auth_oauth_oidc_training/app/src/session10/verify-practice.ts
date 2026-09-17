// セッション 10 の練習問題の解答を検証するスクリプト。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了します。realm の設定は書き換えません。
import { AUDIENCE, ISSUER, fetchAccessToken } from "../session04/bookstore-endpoints.js";
import { mintTokenWithOwnKey, tamperPayload } from "../session04/attacker-forge-tokens.js";
import { decodeJwtPart, loginHeadless } from "../test-helpers/headless-login.js";
import { createApiApp } from "./api-service-app.js";
import { parseChallenge, reportAuthorizationHandling } from "./api-q1-authorization-report.js";
import { SITUATIONS, describeRejection, isHeaderSafe } from "./api-q2-challenge-table.js";
import { auditTokens } from "./api-q3-audience-report.js";
import { JwksCache, isNoMatchingKey } from "./api-q4-jwks-cache.js";
import { HybridVerifier } from "./api-q5-hybrid-verify.js";
import {
  auditRouteProtection,
  createApiAppWithLateMiddleware,
  createApiAppWithReviews,
  listGetPaths,
  unguardedPaths,
} from "./api-q6-route-guard-audit.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

const app = createApiApp();
const alice = await loginHeadless();
const aliceToken = alice.tokens.access_token;
const aliceSub = decodeJwtPart<{ sub?: string }>(aliceToken, 1).sub;
const idToken = alice.tokens.id_token ?? "";
const batchToken = await fetchAccessToken();
const own = await mintTokenWithOwnKey({ issuer: ISSUER, audience: AUDIENCE, subject: "attacker" });

console.log("=== セッション 10 練習問題の検証 ===\n");

// 問題 1: Authorization ヘッダの 10 パターン
console.log("問題 1: Authorization ヘッダの分類");
const rows1 = await reportAuthorizationHandling(app, aliceToken);
check("件数", rows1.length, 10);
check(
  "status の並び",
  rows1.map((row) => row.status),
  [401, 401, 401, 401, 401, 401, 401, 401, 200, 200],
);
check(
  "WWW-Authenticate の error の並び",
  rows1.map((row) => row.challengeError),
  [null, null, null, null, "invalid_request", "invalid_request", "invalid_request", "invalid_request", null, null],
);
check(
  "成功した 2 件にはチャレンジが付かない",
  rows1.slice(8).map((row) => row.hasChallenge),
  [false, false],
);
check("チャレンジの分解", parseChallenge('Bearer realm="api-service", error="invalid_token"'), {
  scheme: "Bearer",
  realm: "api-service",
  error: "invalid_token",
});

// 問題 2: 401 と 403 の対応表
console.log("\n問題 2: 401 と 403 の対応表");
check("ヘッダが無い", describeRejection("ヘッダが無い"), {
  status: 401,
  challenge: 'Bearer realm="api-service"',
  bodyError: "unauthenticated",
});
check("宛先（aud）が違う", describeRejection("宛先（aud）が違う"), {
  status: 401,
  challenge: 'Bearer realm="api-service", error="invalid_token", error_description="The aud claim did not match"',
  bodyError: "invalid_token",
});
check("ロールが足りない", describeRejection("ロールが足りない"), {
  status: 403,
  challenge: null,
  bodyError: "forbidden",
});
check(
  "403 だけがチャレンジを返さない",
  SITUATIONS.filter((situation) => describeRejection(situation).challenge === null),
  ["ロールが足りない"],
);
check(
  "すべてのチャレンジがヘッダに入れてよい文字だけでできている",
  SITUATIONS.every((situation) => {
    const challenge = describeRejection(situation).challenge;
    return challenge === null || isHeaderSafe(challenge);
  }),
  true,
);

// 問題 3: 宛先（aud）の監査
console.log("\n問題 3: 宛先（aud）の監査");
const rows3 = await auditTokens([
  { label: "web-app のアクセストークン", token: aliceToken },
  { label: "batch-worker のアクセストークン", token: batchToken },
  { label: "ID トークン", token: idToken },
]);
check(
  "aud（並べ替え）",
  rows3.map((row) => row.audiences),
  [["api-service"], ["account", "api-service"], ["web-app"]],
);
check(
  "azp",
  rows3.map((row) => row.authorizedParty),
  ["web-app", "batch-worker", "web-app"],
);
check(
  "api-service が受け取るか",
  rows3.map((row) => row.acceptedByApiService),
  [true, true, false],
);
check("ID トークンが拒否された理由", rows3[2]?.reason, "クレームの検証に失敗（aud）");

// 問題 4: JWKS の自作キャッシュ
console.log("\n問題 4: JWKS の自作キャッシュ");
const cache = new JwksCache({ cooldownMs: 0 });
check("1 本目の検証が alice の sub を返す", (await cache.verify(aliceToken))["sub"] === aliceSub, true);
check("JWKS を取りに行った回数", cache.fetchCount, 1);
await cache.verify(batchToken);
check("同じ kid なら取り直さない", cache.fetchCount, 1);
check("手元に持っている kid の数", cache.kids.length >= 1, true);
check("トークンの kid を持っている", cache.kids.includes(decodeJwtPart<{ kid?: string }>(aliceToken, 0).kid ?? ""), true);

let unknownKidError: unknown = undefined;
try {
  await cache.verify(own.token);
} catch (err) {
  unknownKidError = err;
}
check("知らない kid は拒否される", isNoMatchingKey(unknownKidError), true);
check("知らない kid では JWKS を取り直している", cache.fetchCount, 2);

const guarded = new JwksCache({ cooldownMs: 60_000 });
await guarded.verify(aliceToken);
let cooldownMessage = "";
try {
  await guarded.verify(own.token);
} catch (err) {
  cooldownMessage = err instanceof Error ? err.message : String(err);
}
check("cooldown 中は取りに行かない", guarded.fetchCount, 1);
check("cooldown で止めたことが分かる", cooldownMessage.includes("cooldown"), true);

// 署名が合わないだけのトークンでは取り直しが起きない（取り直しても直らない失敗だから）
let tamperedRejected = false;
try {
  await cache.verify(tamperPayload(aliceToken, { sub: "attacker" }));
} catch {
  tamperedRejected = true;
}
check("改ざんされたトークンでは取り直さない", [tamperedRejected, cache.fetchCount], [true, 2]);

// 問題 5: ローカル検証とイントロスペクションの併用
console.log("\n問題 5: ローカル検証とイントロスペクションの併用");
const hybrid = new HybridVerifier({ cacheTtlMs: 60_000 });
const light = await hybrid.verify(aliceToken, { sensitive: false });
check("軽い操作の出どころ", light.source, "local");
check("軽い操作では生死を判断しない", light.active, null);
check("問い合わせ回数", hybrid.introspectionCalls, 0);

const heavy = await hybrid.verify(aliceToken, { sensitive: true });
check("重い操作の出どころ", heavy.source, "introspection");
check("重い操作の active", heavy.active, true);
check("問い合わせ回数", hybrid.introspectionCalls, 1);

const heavyAgain = await hybrid.verify(aliceToken, { sensitive: true });
check("2 回目はキャッシュを使う", heavyAgain.source, "introspection-cache");
check("問い合わせ回数は増えない", hybrid.introspectionCalls, 1);

const noCache = new HybridVerifier({ cacheTtlMs: 0 });
await noCache.verify(aliceToken, { sensitive: true });
await noCache.verify(aliceToken, { sensitive: true });
check("キャッシュ無しなら毎回問い合わせる", noCache.introspectionCalls, 2);

let localRejected = false;
try {
  await noCache.verify(own.token, { sensitive: true });
} catch {
  localRejected = true;
}
check("ローカル検証で落ちたトークンは問い合わせない", [localRejected, noCache.introspectionCalls], [true, 2]);

// 問題 6: 保護され忘れたルートが無いかの自動点検
console.log("\n問題 6: 保護され忘れたルートが無いかの自動点検");
check("登録済みの GET ルート", listGetPaths(app), ["/api/inventory", "/api/orders", "/api/whoami", "/health"]);
check("保護され忘れたパス", unguardedPaths(await auditRouteProtection(app)), []);

const extended = createApiAppWithReviews();
check("あとから足したルートも列挙される", listGetPaths(extended).includes("/api/reviews"), true);
check("あとから足したルートも保護されている", unguardedPaths(await auditRouteProtection(extended)), []);
const reviews = await extended.request("/api/reviews", { headers: { authorization: `Bearer ${aliceToken}` } });
check("本物のトークンなら 200", reviews.status, 200);
check(
  "応答の sub がトークンの sub と一致",
  ((await reviews.json()) as { subject?: string }).subject === aliceSub,
  true,
);

const late = createApiAppWithLateMiddleware();
check("ミドルウェアの登録が遅いと保護漏れが検出される", unguardedPaths(await auditRouteProtection(late)), [
  "/api/whoami",
]);
check("保護漏れのパスはトークン無しで 200 を返す", (await late.request("/api/whoami")).status, 200);

console.log(
  failures === 0
    ? "\n練習問題のすべての検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
