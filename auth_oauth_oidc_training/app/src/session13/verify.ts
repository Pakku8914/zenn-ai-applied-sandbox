// セッション 13 の自己検証スクリプト。
// realm の設定は一切書き換えません（DPoP は Keycloak 26.7.3 の既定で有効です）。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了するため、人が出力を読んで判断する必要はありません。
import { calculateJwkThumbprint, exportJWK, generateKeyPair } from "jose";
import type { JWTPayload } from "jose";
import { ISSUER, TOKEN_ENDPOINT } from "../session04/bookstore-endpoints.js";
import { createApiApp } from "../session10/api-service-app.js";
import { decodeJwtPart } from "../test-helpers/headless-login.js";
import { basicCredentials, buildTokenRequest, requestClientCredentials } from "./batch-worker-client.js";
import { createDpopKey } from "./bookstore-dpop.js";
import { ProofReplayGuard, confirmationThumbprint, sameRequestUrl, verifyDpopProof } from "./api-service-dpop.js";
import { apiUrl } from "./api-service-dpop-app.js";
import { NIGHTLY_ORDER_SUMMARY, auditServiceAccount, fetchServiceAccountFacts } from "./batch-worker-scope-audit.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

console.log("=== セッション 13 の検証 ===\n");

// 1. Client Credentials（利用者が関わらないフロー）
console.log("1. Client Credentials");
const bearer = await requestClientCredentials();
check("status", bearer.status, 200);
check("返るキー", bearer.keys, [
  "access_token",
  "expires_in",
  "not-before-policy",
  "refresh_expires_in",
  "scope",
  "token_type",
]);
check("token_type", bearer.tokenType, "Bearer");
check("refresh_token は返らない", bearer.hasRefreshToken, false);
check("expires_in", bearer.expiresIn, 300);
check("scope", bearer.scope, "email profile");

// 2. 秘密の置き場所を変えても、返ってくるものは同じ
console.log("\n2. client_secret_basic と client_secret_post");
const post = await requestClientCredentials({ method: "client_secret_post" });
check("client_secret_post でも status は同じ", post.status, 200);
check("client_secret_post でも token_type は同じ", post.tokenType, "Bearer");
const basicRequest = buildTokenRequest({ method: "client_secret_basic" });
const postRequest = buildTokenRequest({ method: "client_secret_post" });
check(
  "basic は Authorization ヘッダに置く",
  basicRequest.headers["authorization"],
  basicCredentials("batch-worker", "batch-worker-secret"),
);
check("basic はボディに秘密を入れない", basicRequest.body.has("client_secret"), false);
check("post は Authorization ヘッダを使わない", postRequest.headers["authorization"], undefined);
check("post はボディに秘密を入れる", postRequest.body.get("client_secret"), "batch-worker-secret");

// 3. 認可サーバーが申告している方式
console.log("\n3. discovery の申告");
const discovery = (await (await fetch(`${ISSUER}/.well-known/openid-configuration`)).json()) as Record<
  string,
  unknown
>;
check("クライアント認証の方式", (discovery["token_endpoint_auth_methods_supported"] as string[]).slice().sort(), [
  "client_secret_basic",
  "client_secret_jwt",
  "client_secret_post",
  "private_key_jwt",
  "tls_client_auth",
]);
check(
  "DPoP の署名方式に ES256 が含まれる",
  (discovery["dpop_signing_alg_values_supported"] as string[]).includes("ES256"),
  true,
);
check("証明書に紐づけたトークンに対応している", discovery["tls_client_certificate_bound_access_tokens"], true);

// 4. DPoP の鍵ペアと公開鍵
console.log("\n4. DPoP の鍵ペア");
const key = await createDpopKey();
check("公開鍵のフィールド", Object.keys(key.publicJwk).sort(), ["crv", "kty", "x", "y"]);
check("kty", key.publicJwk.kty, "EC");
check("crv", key.publicJwk.crv, "P-256");
check("サムプリントの長さ（SHA-256 の base64url）", key.thumbprint.length, 43);
check("サムプリントは公開鍵だけから計算できる", await calculateJwkThumbprint(key.publicJwk, "sha256"), key.thumbprint);

let exportable = "書き出せた";
try {
  const fragile = await generateKeyPair("ES256");
  await exportJWK(fragile.privateKey);
} catch {
  exportable = "書き出せない";
}
check("extractable を付けない鍵は JWK にできない", exportable, "書き出せない");

// 5. DPoP を付けるとトークンが鍵に縛られる（本章の山場）
console.log("\n5. DPoP 付きのトークン要求");
const tokenProof = await key.createProof({ htm: "POST", htu: TOKEN_ENDPOINT });
const dpop = await requestClientCredentials({ dpopProof: tokenProof });
check("status", dpop.status, 200);
check("token_type が Bearer から DPoP に変わる", dpop.tokenType, "DPoP");
const dpopClaims = decodeJwtPart<JWTPayload>(dpop.accessToken, 1);
check("cnf.jkt が公開鍵のサムプリントと一致する", confirmationThumbprint(dpopClaims), key.thumbprint);
const cnf = dpopClaims["cnf"] as Record<string, unknown>;
check("cnf のキー", Object.keys(cnf).sort(), ["jkt", "kc-jkt-type"]);
check("kc-jkt-type", cnf["kc-jkt-type"], "DPoP");
check(
  "DPoP ヘッダを付けないトークンに cnf は無い",
  confirmationThumbprint(decodeJwtPart<JWTPayload>(bearer.accessToken, 1)),
  undefined,
);

// 6. proof の 5 つの観点
console.log("\n6. proof の検証");
const nowSec = Math.floor(Date.now() / 1000);
const summaryUrl = apiUrl("/api/summary");
const ordersUrl = apiUrl("/api/orders");

async function reasonOf(
  proof: string,
  over: {
    method?: string;
    url?: string;
    accessToken?: string;
    expectedThumbprint?: string;
    now?: number;
    guard?: ProofReplayGuard;
  } = {},
): Promise<string> {
  const result = await verifyDpopProof({
    proof,
    method: over.method ?? "GET",
    url: over.url ?? summaryUrl,
    accessToken: over.accessToken ?? dpop.accessToken,
    expectedThumbprint: over.expectedThumbprint ?? key.thumbprint,
    now: over.now ?? nowSec,
    guard: over.guard,
  });
  return result.ok ? "ok" : result.reason;
}

const goodProof = await key.createProof({ htm: "GET", htu: summaryUrl, accessToken: dpop.accessToken, iat: nowSec });
check("正しい proof", await reasonOf(goodProof), "ok");
check("クエリが付いた URL でも通る", await reasonOf(goodProof, { url: `${summaryUrl}?limit=5` }), "ok");
check("JWT の形ではない", await reasonOf("not-a-proof"), "proof_malformed");

const parts = goodProof.split(".");
const tampered = `${parts[0] ?? ""}.${parts[1] ?? ""}.AAAA${parts[2] ?? ""}`;
check("署名を書き換えた proof", await reasonOf(tampered), "proof_signature");

const attacker = await createDpopKey();
const attackerProof = await attacker.createProof({
  htm: "GET",
  htu: summaryUrl,
  accessToken: dpop.accessToken,
  iat: nowSec,
});
check("攻撃者が自分の鍵で作った proof", await reasonOf(attackerProof), "thumbprint_mismatch");

const postMethodProof = await key.createProof({
  htm: "POST",
  htu: summaryUrl,
  accessToken: dpop.accessToken,
  iat: nowSec,
});
check("メソッドが違う proof", await reasonOf(postMethodProof), "htm_mismatch");

const otherPathProof = await key.createProof({
  htm: "GET",
  htu: ordersUrl,
  accessToken: dpop.accessToken,
  iat: nowSec,
});
check("URL が違う proof", await reasonOf(otherPathProof), "htu_mismatch");

const otherTokenProof = await key.createProof({
  htm: "GET",
  htu: summaryUrl,
  accessToken: bearer.accessToken,
  iat: nowSec,
});
check("別のトークンのハッシュが入った proof", await reasonOf(otherTokenProof), "ath_mismatch");

const oldProof = await key.createProof({
  htm: "GET",
  htu: summaryUrl,
  accessToken: dpop.accessToken,
  iat: nowSec - 120,
});
check("古い proof", await reasonOf(oldProof), "iat_out_of_window");

const guard = new ProofReplayGuard();
const onceProof = await key.createProof({
  htm: "GET",
  htu: summaryUrl,
  accessToken: dpop.accessToken,
  iat: nowSec,
  jti: "proof-once",
});
check("1 回目は通る", await reasonOf(onceProof, { guard }), "ok");
check("同じ proof の 2 回目", await reasonOf(onceProof, { guard }), "jti_replayed");
check("覚えている jti の数", guard.size, 1);
check("クエリとフラグメントは比べない", sameRequestUrl(`${summaryUrl}?a=1#x`, summaryUrl), true);
check("パスが違えば別物", sameRequestUrl(ordersUrl, summaryUrl), false);

// 7. 盗まれたトークンの被害範囲（Bearer との対比）
console.log("\n7. 盗まれたトークンの被害範囲");
const bearerApi = createApiApp();
const callBearer = async (token: string): Promise<Response> =>
  await bearerApi.request("http://api-service:4100/api/whoami", { headers: { authorization: `Bearer ${token}` } });

check("Bearer トークンは持っているだけで通る", (await callBearer(bearer.accessToken)).status, 200);
check("DPoP トークンは自分の鍵では使えない", await reasonOf(attackerProof), "thumbprint_mismatch");
check("cnf を見ない API は DPoP のトークンも通してしまう", (await callBearer(dpop.accessToken)).status, 200);

// 8. サービスアカウントの権限の棚卸し
console.log("\n8. サービスアカウントの権限");
const facts = await fetchServiceAccountFacts();
check("クライアント", facts.client, "batch-worker");
check("載っているスコープ", facts.scopes, ["email", "profile"]);
check("aud", facts.audiences, ["account", "api-service"]);
check("account クライアントのロールが付いている", facts.resourceClients.includes("account"), true);

const report = auditServiceAccount(NIGHTLY_ORDER_SUMMARY, facts);
check("足りない権限", report.missingScopes, ["orders:read"]);
check("要らない権限", report.extraScopes, ["email", "profile"]);
check("宛先は足りている", report.missingAudiences, []);
check("判定", report.verdict, "mismatched");

// 9. クライアント認証に失敗したときの応答（本文「よくあるエラー」の根拠）
console.log("\n9. クライアント認証の失敗");
async function tokenError(body: Record<string, string>): Promise<string> {
  const res = await fetch(TOKEN_ENDPOINT, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "client_credentials", ...body }),
  });
  const payload = (await res.json()) as Record<string, unknown>;
  return `${res.status} ${String(payload["error"])} / ${String(payload["error_description"])}`;
}

check(
  "client_secret を間違える",
  await tokenError({ client_id: "batch-worker", client_secret: "wrong-secret" }),
  "401 unauthorized_client / Invalid client or Invalid client credentials",
);
check(
  "クライアント認証を付けない",
  await tokenError({ client_id: "batch-worker" }),
  "401 unauthorized_client / Invalid client or Invalid client credentials",
);
check(
  "公開クライアントで Client Credentials を試す",
  await tokenError({ client_id: "web-app" }),
  "401 unauthorized_client / Public client not allowed to retrieve service account",
);
check(
  "登録されていない client_id",
  await tokenError({ client_id: "ghost-worker", client_secret: "x" }),
  "401 invalid_client / Invalid client or Invalid client credentials",
);

console.log(
  failures === 0 ? "\nセッション 13 のすべての検証に成功しました。" : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
