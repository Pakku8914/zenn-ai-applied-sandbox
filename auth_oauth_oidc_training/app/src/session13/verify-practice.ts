// セッション 13 の練習問題の解答を検証するスクリプト。
// realm の設定は書き換えません。期待値と一致しなければ非 0 で終了します。
import { SignJWT } from "jose";
import { ISSUER, TOKEN_ENDPOINT } from "../session04/bookstore-endpoints.js";
import { decodeJwtPart } from "../test-helpers/headless-login.js";
import { requestClientCredentials } from "./batch-worker-client.js";
import { createDpopKey } from "./bookstore-dpop.js";
import { apiUrl } from "./api-service-dpop-app.js";
import { PROOF_IAT_WINDOW } from "./api-service-dpop.js";
import { CLIENT_ASSERTION_TYPE, createAssertionSigner } from "./batch-worker-private-key-jwt.js";
import { fetchServiceAccountFacts } from "./batch-worker-scope-audit.js";
import { AUTH_METHOD_FACTS, probeAll, toMarkdown as authMarkdown } from "./batch-q1-client-auth-matrix.js";
import { compareHtu, htuMatches } from "./api-q2-htu-compare.js";
import { JOBS, auditAll, remediation, splitAdvice, summarize } from "./batch-q3-service-account-audit.js";
import { createDpopApi, extractDpopToken } from "./api-q4-dpop-middleware.js";
import { NonceIssuer, createNonceApi } from "./api-q4-dpop-nonce.js";
import { countStopped, simulateTheft } from "./attacker-q5-theft-simulation.js";
import { verifyClientAssertion } from "./api-q6-client-assertion-verify.js";
import { describeCredentials, renewalPlan, summarizeShape } from "./batch-q7-credentials-shape.js";
import { comparePlacements, exposure, placementOf } from "./batch-q8-secret-placement.js";
import { SCENARIOS, chooseAll, decisionTable, groupByAxis } from "./batch-q9-auth-method-choice.js";
import { REQUIRED_CLAIMS, auditAssertions, buildAssertionForm, checkLifetime } from "./batch-q10-assertion-builder.js";
import { checkFreshness, jtiSequence } from "./api-q11-proof-freshness.js";
import { MAX_REJECT_RATE, MIN_OBSERVED_DAYS, decide, metricOf, readyToRequire, tally } from "./api-q12-dpop-migration.js";
import type { JWK } from "jose";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}
const bodyOf = async (res: Response): Promise<Record<string, unknown>> =>
  (await res.json()) as Record<string, unknown>;

console.log("=== セッション 13 練習問題の検証 ===\n");

/** 時刻に依存する検査は、この 1 つの値をそろえて使います */
const q13Now = Math.floor(Date.now() / 1000);

// 問題 1: クライアント認証の 4 方式を並べる
console.log("問題 1: クライアント認証の 4 方式");
check(
  "並べた方式",
  AUTH_METHOD_FACTS.map((fact) => fact.method),
  ["client_secret_basic", "client_secret_post", "private_key_jwt", "tls_client_auth"],
);
check(
  "秘密そのものが外に出るか",
  AUTH_METHOD_FACTS.map((fact) => fact.secretLeavesTheClient),
  [true, true, false, false],
);
check(
  "鍵ペアが要るか",
  AUTH_METHOD_FACTS.map((fact) => fact.needsKeyPair),
  [false, false, true, true],
);
check(
  "サンドボックスで試せるか",
  AUTH_METHOD_FACTS.map((fact) => fact.worksInSandbox),
  [true, true, true, false],
);
check("表の行数（見出し 2 行 + 4 方式）", authMarkdown().split("\n").length, 6);

const probes = await probeAll();
check(
  "どちらの方式でも 200 で Bearer が返る",
  probes.map((row) => `${row.status}/${row.tokenType}`),
  ["200/Bearer", "200/Bearer"],
);
check(
  "秘密が通る場所",
  probes.map((row) => `${row.sentInHeader ? "ヘッダ" : "-"}/${row.sentInBody ? "ボディ" : "-"}`),
  ["ヘッダ/-", "-/ボディ"],
);

// 前半 問題 2: Client Credentials の応答の形
console.log("\n前半 問題 2: Client Credentials の応答の形");
const shape = await describeCredentials();
check("status", shape.status, 200);
check("返るキー", shape.keys, [
  "access_token",
  "expires_in",
  "not-before-policy",
  "refresh_expires_in",
  "scope",
  "token_type",
]);
check("refresh_token は返らない", shape.hasRefreshToken, false);
check("aud の型", shape.audienceKind, "array");
check("配列にそろえた aud", shape.audiences, ["account", "api-service"]);
check("再取得の作戦", shape.renewal, "re-request");
check("refresh_token があれば作戦は変わる", renewalPlan(true), "refresh");
check(
  "1 行の要約",
  summarizeShape(shape),
  "token_type=Bearer refresh_token=なし expires_in=300 aud=array(account,api-service) renewal=re-request",
);

// 前半 問題 3: 秘密の置き場所
console.log("\n前半 問題 3: 秘密の置き場所");
const placements = comparePlacements();
check("basic は Authorization ヘッダに置く", placements.basic.secretInHeader, true);
check("basic はボディに秘密を入れない", placements.basic.secretInBody, false);
check("post は Authorization ヘッダを使わない", placements.post.secretInHeader, false);
check("post のボディのキー", placements.post.bodyKeys, ["client_id", "client_secret", "grant_type"]);
check("basic のボディのキー", placements.basic.bodyKeys, ["client_id", "grant_type"]);
check("どちらも URL には載せない", [placements.basic.secretInUrl, placements.post.secretInUrl], [false, false]);
check("違うのは置き場所だけ", placements.differences, [
  "header",
  "bodyKeys",
  "secretInHeader",
  "secretInBody",
]);
check("強さは同じ", placements.sameStrength, true);
check("basic が残りうる記録", exposure(placements.basic), ["リクエストヘッダを記録するプロキシ"]);
check("post が残りうる記録", exposure(placementOf("client_secret_post")), [
  "リクエストボディをダンプするデバッグ設定",
]);

// 前半 問題 4: 制約から方式を選ぶ
console.log("\n前半 問題 4: 制約から方式を選ぶ");
check("3 軸への分類", groupByAxis(), [
  { axis: "秘密を送る", methods: ["client_secret_basic", "client_secret_post"] },
  { axis: "秘密で署名する", methods: ["private_key_jwt"] },
  { axis: "通信路に紐づける", methods: ["tls_client_auth"] },
]);
const choices = chooseAll();
check("シナリオの数", SCENARIOS.length, 3);
check(
  "選んだ方式",
  choices.map((choice) => choice.method),
  ["tls_client_auth", "private_key_jwt", "client_secret_basic"],
);
check(
  "見送った方式の数",
  choices.map((choice) => choice.rejected.length),
  [0, 1, 2],
);
check(
  "秘密の共有範囲が広いときだけ注記が付く",
  choices.map((choice) => choice.note !== ""),
  [false, false, true],
);
check("決定の記録の行数（見出し 2 行 + 3 件）", decisionTable().split("\n").length, 5);

// 前半 問題 5: assertion の組み立てと点検
console.log("\n前半 問題 5: assertion の組み立てと点検");
check("必須クレーム", REQUIRED_CLAIMS, ["iss", "sub", "aud", "jti", "exp"]);
const audits = await auditAssertions(q13Now);
check(
  "3 本の判定",
  audits.map((audit) => audit.verdict),
  ["ok", "too_long_lived", "missing_exp"],
);
check(
  "送ってよいのは 1 本だけ",
  audits.map((audit) => audit.sendable),
  [true, false, false],
);
check(
  "欠けている必須クレーム",
  audits.map((audit) => audit.missing.join(" ")),
  ["", "", "exp"],
);
const goodAssertion = await (await createAssertionSigner()).build({ iat: q13Now, jti: "assertion-form" });
const form = buildAssertionForm(goodAssertion);
check("フォームのキー", [...form.keys()].sort(), [
  "client_assertion",
  "client_assertion_type",
  "client_id",
  "grant_type",
]);
check("client_secret はフォームに入らない", form.has("client_secret"), false);
check("client_assertion_type", form.get("client_assertion_type"), CLIENT_ASSERTION_TYPE);
check("既定の上限（300 秒）では通る", checkLifetime(goodAssertion), "ok");
check("上限を 30 秒に絞ると弾かれる", checkLifetime(goodAssertion, 30), "too_long_lived");

// 問題 2: htu の突き合わせ
console.log("\n問題 2: htu の突き合わせ");
const SUMMARY_URL = apiUrl("/api/summary");
const htuCases: ReadonlyArray<readonly [string, string]> = [
  [SUMMARY_URL, SUMMARY_URL],
  [SUMMARY_URL, `${SUMMARY_URL}?limit=5`],
  [`${SUMMARY_URL}#top`, SUMMARY_URL],
  ["http://API-SERVICE:4100/api/summary", SUMMARY_URL],
  ["http://api-service:80/api/summary", "http://api-service/api/summary"],
  ["http://api-service:4200/api/summary", SUMMARY_URL],
  ["https://api-service:4100/api/summary", SUMMARY_URL],
  ["http://other-api:4100/api/summary", SUMMARY_URL],
  ["http://api-service:4100/API/summary", SUMMARY_URL],
  [`${SUMMARY_URL}/`, SUMMARY_URL],
  ["/api/summary", SUMMARY_URL],
];
check(
  "11 ケースの判定",
  htuCases.map(([claimed, actual]) => compareHtu(claimed, actual)),
  ["match", "match", "match", "match", "match", "port", "scheme", "host", "path", "path", "malformed"],
);
check("クエリは比べない", htuMatches(SUMMARY_URL, `${SUMMARY_URL}?limit=5`), true);
check("末尾のスラッシュは別物", htuMatches(`${SUMMARY_URL}/`, SUMMARY_URL), false);

// 問題 3: サービスアカウントの権限の棚卸し
console.log("\n問題 3: サービスアカウントの権限の棚卸し");
const facts = await fetchServiceAccountFacts();
const reports = auditAll(JOBS, facts);
check(
  "3 本のバッチの判定",
  reports.map((report) => report.verdict),
  ["mismatched", "mismatched", "excessive"],
);
check(
  "足りない権限",
  reports.map((report) => report.missingScopes.join(" ")),
  ["orders:read", "orders:read orders:write", ""],
);
check(
  "要らない権限",
  reports.map((report) => report.extraScopes.join(" ")),
  ["email profile", "email profile", "profile"],
);
const nightly = reports[0];
const mail = reports[2];
if (nightly === undefined || mail === undefined) throw new Error("報告が 3 件そろっていません");
check("夜間バッチでやること", remediation(nightly), [
  { action: "add-scope", target: "orders:read" },
  { action: "remove-scope", target: "email" },
  { action: "remove-scope", target: "profile" },
]);
check("メール送信でやること", remediation(mail), [{ action: "remove-scope", target: "profile" }]);
const advice = splitAdvice(JOBS);
check("アカウントを分けるべきか", advice.advice, "separate");
check("必要な権限の集合の種類", advice.distinctScopeSets, 3);
check(
  "1 行の要約",
  summarize(mail),
  "mail-sender [excessive] remove-scope:profile",
);

// 問題 4: DPoP 検証ミドルウェア
console.log("\n問題 4: DPoP 検証ミドルウェア");
check("ヘッダが無い", extractDpopToken(undefined), { ok: false, reason: "missing" });
check("Bearer スキーム", extractDpopToken("Bearer a.b.c"), { ok: false, reason: "wrong_scheme" });
check("DPoP スキーム", extractDpopToken("DPoP a.b.c"), { ok: true, token: "a.b.c" });
check("スキームは大文字小文字を区別しない", extractDpopToken("dpop a.b.c"), { ok: true, token: "a.b.c" });
check("DPoP だけ", extractDpopToken("DPoP"), { ok: false, reason: "malformed" });

const key = await createDpopKey();
const bound = await requestClientCredentials({
  dpopProof: await key.createProof({ htm: "POST", htu: TOKEN_ENDPOINT }),
});
const plain = await requestClientCredentials();
const api = createDpopApi();
const summaryUrl = apiUrl("/api/summary");
const ordersUrl = apiUrl("/api/orders");
const callDpop = async (url: string, token: string, proof: string): Promise<Response> =>
  await api.request(url, { headers: { authorization: `DPoP ${token}`, dpop: proof } });

check("/health はトークン無しで 200", (await api.request(apiUrl("/health"))).status, 200);
const noToken = await api.request(summaryUrl);
check("トークン無しの status", noToken.status, 401);
check("トークン無しのチャレンジ", noToken.headers.get("www-authenticate"), 'DPoP realm="api-service", algs="ES256"');

const summaryProof = await key.createProof({ htm: "GET", htu: summaryUrl, accessToken: bound.accessToken });
const summary = await callDpop(summaryUrl, bound.accessToken, summaryProof);
const summaryBody = await bodyOf(summary);
check("正しい proof なら 200", summary.status, 200);
check("クライアント", summaryBody["client"], "batch-worker");
check("応答に載る jkt", summaryBody["jkt"], key.thumbprint);
check("aud（並べ替え）", (summaryBody["audiences"] as string[]).slice().sort(), ["account", "api-service"]);

const replayed = await callDpop(summaryUrl, bound.accessToken, summaryProof);
check("同じ proof の 2 回目は 401", replayed.status, 401);
check("エラーコード", (await bodyOf(replayed))["error"], "invalid_dpop_proof");
check(
  "チャレンジ",
  replayed.headers.get("www-authenticate"),
  'DPoP realm="api-service", algs="ES256", error="invalid_dpop_proof", error_description="The DPoP proof is not acceptable (jti_replayed)"',
);

const ordersProof = await key.createProof({ htm: "GET", htu: ordersUrl, accessToken: bound.accessToken });
check("別の URL 向けの proof は使えない", (await callDpop(summaryUrl, bound.accessToken, ordersProof)).status, 401);
const orders = await callDpop(ordersUrl, bound.accessToken, ordersProof);
check("正しい proof なら /api/orders も 200", orders.status, 200);
check("注文の件数", ((await bodyOf(orders))["orders"] as unknown[]).length, 4);

const twoProofs = await api.request(summaryUrl, {
  headers: [
    ["authorization", `DPoP ${bound.accessToken}`],
    ["dpop", await key.createProof({ htm: "GET", htu: summaryUrl, accessToken: bound.accessToken })],
    ["dpop", await key.createProof({ htm: "GET", htu: summaryUrl, accessToken: bound.accessToken })],
  ],
});
check("proof が 2 つあると 401", twoProofs.status, 401);

const notBound = await callDpop(
  summaryUrl,
  plain.accessToken,
  await key.createProof({ htm: "GET", htu: summaryUrl, accessToken: plain.accessToken }),
);
check("鍵に縛られていないトークンは受け付けない", notBound.status, 401);
check("エラーコード", (await bodyOf(notBound))["error"], "invalid_token");

const wrongScheme = await api.request(summaryUrl, {
  headers: {
    authorization: `Bearer ${bound.accessToken}`,
    dpop: await key.createProof({ htm: "GET", htu: summaryUrl, accessToken: bound.accessToken }),
  },
});
check("Bearer スキームでは受け付けない", wrongScheme.status, 401);
check("エラーコード", (await bodyOf(wrongScheme))["error"], "invalid_token");

// 問題 4 の発展: サーバーが配る nonce
console.log("\n問題 4 の発展: サーバーが配る nonce");
let fakeNow = Math.floor(Date.now() / 1000);
const nonces = new NonceIssuer();
const nonceApi = createNonceApi({ nonces, now: () => fakeNow });
const callNonce = async (nonce?: string): Promise<Response> =>
  await nonceApi.request(summaryUrl, {
    headers: {
      authorization: `DPoP ${bound.accessToken}`,
      dpop: await key.createProof({
        htm: "GET",
        htu: summaryUrl,
        accessToken: bound.accessToken,
        iat: fakeNow,
        nonce,
      }),
    },
  });

const first = await callNonce();
check("nonce 無しは 401", first.status, 401);
check("エラーコード", (await bodyOf(first))["error"], "use_dpop_nonce");
const issued = first.headers.get("dpop-nonce");
check("拒否と同時に nonce が渡される", typeof issued === "string" && issued.length > 0, true);

const second = await callNonce(issued ?? "");
check("渡された nonce を入れると 200", second.status, 200);
check("応答に載る nonce", (await bodyOf(second))["nonce"], issued);
check("同じ nonce で新しい proof を作れば通る", (await callNonce(issued ?? "")).status, 200);
check("知らない nonce は 401", (await callNonce("not-issued-by-me")).status, 401);

fakeNow += 120;
const stale = await callNonce(issued ?? "");
check("期限切れの nonce は 401", stale.status, 401);
check("新しい nonce が渡される", stale.headers.get("dpop-nonce") !== issued, true);

// 問題 5: 盗まれたトークンの被害範囲
console.log("\n問題 5: 盗まれたトークンの被害範囲");
const rows = await simulateTheft();
check("試した回数", rows.length, 6);
check(
  "応答",
  rows.map((row) => row.status),
  [200, 200, 401, 401, 401, 401],
);
check(
  "エラーコード",
  rows.map((row) => row.error),
  ["", "", "invalid_dpop_proof", "invalid_dpop_proof", "invalid_token", "invalid_dpop_proof"],
);
check(
  "結果の読み分け",
  rows.map((row) => row.outcome),
  [
    "盗んだだけで通る",
    "サーバーが見ていないので通る",
    "鍵が無いので通らない",
    "鍵が無いので通らない",
    "スキームが違うので通らない",
    "鍵が無いので通らない",
  ],
);
check("止められた件数", countStopped(rows), 4);

// 問題 6: assertion を認可サーバー側で検証する
console.log("\n問題 6: assertion を認可サーバー側で検証する");
const q6Now = q13Now;
const signer = await createAssertionSigner();
const otherSigner = await createAssertionSigner("other-key-1");
const keys = new Map<string, JWK>([["batch-worker", signer.publicJwk]]);
const seenJtis = new Set<string>();
check("認可サーバーに渡すのは公開鍵だけ", Object.keys(signer.publicJwk).sort(), ["e", "kid", "kty", "n"]);
check("登録されたクライアントの数", keys.size, 1);

async function assertionReason(
  assertion: string,
  over: {
    now?: number;
    formClientId?: string;
    acceptedAudiences?: readonly string[];
    seenJtis?: Set<string>;
  } = {},
): Promise<string> {
  const result = await verifyClientAssertion(assertion, {
    keys,
    acceptedAudiences: over.acceptedAudiences ?? [TOKEN_ENDPOINT, ISSUER],
    now: over.now ?? q6Now,
    seenJtis: over.seenJtis ?? seenJtis,
    formClientId: over.formClientId,
  });
  return result.ok ? `ok:${result.clientId}` : result.reason;
}

const good = await signer.build({ iat: q6Now, jti: "assertion-1" });
const goodHeader = decodeJwtPart<{ alg?: string; kid?: string }>(good, 0);
check("alg", goodHeader.alg, "RS256");
check("kid", goodHeader.kid, "batch-worker-key-1");
check("秘密は 1 文字も入っていない", good.includes("batch-worker-secret"), false);
check("正しい assertion", await assertionReason(good), "ok:batch-worker");
check("同じ assertion の 2 回目", await assertionReason(good), "jti_replayed");
check("別の入れ物なら同じ jti も通る", await assertionReason(good, { seenJtis: new Set() }), "ok:batch-worker");
check("覚えている jti の数", seenJtis.size, 1);

check(
  "フォームの client_id と食い違う",
  await assertionReason(await signer.build({ iat: q6Now, jti: "assertion-2" }), { formClientId: "web-app" }),
  "issuer_mismatch",
);
check(
  "公開鍵を登録していないクライアント",
  await assertionReason(await signer.build({ iat: q6Now, jti: "assertion-3", clientId: "ghost-worker" })),
  "unknown_client",
);
check(
  "宛先が違う",
  await assertionReason(
    await signer.build({
      iat: q6Now,
      jti: "assertion-4",
      audience: "http://keycloak:8080/realms/other/protocol/openid-connect/token",
    }),
  ),
  "audience_mismatch",
);
check("期限が切れている", await assertionReason(await signer.build({ iat: q6Now - 600, jti: "assertion-5" })), "expired");
check(
  "寿命が長すぎる",
  await assertionReason(await signer.build({ iat: q6Now, jti: "assertion-6", lifetimeSeconds: 3600 })),
  "too_long_lived",
);
check(
  "登録した鍵と違う鍵で署名されている",
  await assertionReason(await otherSigner.build({ iat: q6Now, jti: "assertion-7" })),
  "signature",
);

// 共有秘密（HS256）で署名した assertion は private_key_jwt として認めません
const hs256 = await new SignJWT({
  iss: "batch-worker",
  sub: "batch-worker",
  aud: TOKEN_ENDPOINT,
  jti: "assertion-8",
  iat: q6Now,
  exp: q6Now + 60,
})
  .setProtectedHeader({ alg: "HS256" })
  .sign(new TextEncoder().encode("batch-worker-secret-batch-worker-secret"));
check("HS256 で署名されている", await assertionReason(hs256), "alg_not_allowed");
check("JWT の形ではない", await assertionReason("not-a-jwt"), "malformed");

// 後半 問題 1: proof の鮮度と使い捨て
console.log("\n後半 問題 1: proof の鮮度と使い捨て");
const W = PROOF_IAT_WINDOW;
const iats: ReadonlyArray<number | undefined> = [q13Now, q13Now - W, q13Now - W - 1, q13Now + W, q13Now + W + 1, undefined];
check(
  "6 ケースの判定",
  iats.map((iat) => checkFreshness(iat, q13Now)),
  ["fresh", "fresh", "too_old", "fresh", "too_new", "no_iat"],
);
check("窓は引数で上書きできる", checkFreshness(q13Now - 31, q13Now, 60), "fresh");
check("jti は 2 回目だけ拒まれ、窓を十分に過ぎると忘れられる", jtiSequence(q13Now), [
  "first_time",
  "replayed",
  "first_time",
  "first_time",
]);
// 本文の proof を実際に作り、その iat が同じ判定を通ることを確かめます
const realProof = await key.createProof({ htm: "GET", htu: summaryUrl, iat: q13Now });
const realIat = (JSON.parse(Buffer.from(realProof.split(".")[1] ?? "", "base64url").toString()) as { iat?: number }).iat;
check("実物の proof の iat", checkFreshness(realIat, q13Now), "fresh");

// 後半 問題 6: Bearer から DPoP への段階移行
console.log("\n後半 問題 6: Bearer から DPoP への段階移行");
const unbound = { scheme: "Bearer", bound: false, proofValid: false } as const;
const boundBearer = { scheme: "Bearer", bound: true, proofValid: false } as const;
const dpopOk = { scheme: "DPoP", bound: true, proofValid: true } as const;
const dpopBad = { scheme: "DPoP", bound: true, proofValid: false } as const;
check(
  "observe は 1 件も落とさない",
  [unbound, boundBearer, dpopOk, dpopBad].map((f) => decide("observe", f).allow),
  [true, true, true, true],
);
check(
  "prefer は DPoP を名乗ったものだけ落とす",
  [unbound, boundBearer, dpopOk, dpopBad].map((f) => decide("prefer", f).allow),
  [true, true, true, false],
);
check(
  "require は Bearer を落とす",
  [unbound, boundBearer, dpopOk, dpopBad].map((f) => decide("require", f).allow),
  [false, false, true, false],
);
check(
  "計測項目への割り当て",
  [unbound, boundBearer, dpopOk, dpopBad].map((f) => decide("observe", f).metric),
  ["bearer_unbound", "bearer_bound", "dpop_ok", "dpop_rejected"],
);
check("拒否率と観測期間のしきい値", [MAX_REJECT_RATE, MIN_OBSERVED_DAYS], [0.01, 14]);

const week1 = tally([unbound, unbound, dpopOk, dpopBad]);
check("観測 1 週目の集計", week1, { bearer_unbound: 2, bearer_bound: 0, dpop_ok: 1, dpop_rejected: 1 });
const notReady = readyToRequire(week1, 7);
check("1 週目はまだ必須化できない", notReady.ready, false);
check("落ちた理由", notReady.blockers, ["unbound_bearer", "high_reject", "short_window"]);
check("拒否率", notReady.rejectRate, 0.5);

const week4 = tally(Array.from({ length: 200 }, () => dpopOk));
check("4 週目の集計", week4, { bearer_unbound: 0, bearer_bound: 0, dpop_ok: 200, dpop_rejected: 0 });
const ready = readyToRequire(week4, 21);
check("4 週目は必須化できる", ready, { ready: true, blockers: [], rejectRate: 0 });

check("bearer-only では制約付きトークンも素通りする", decide("bearer-only", boundBearer), {
  allow: true,
  metric: "bearer_bound",
});
check("分類は判定と独立している", [unbound, dpopBad].map(metricOf), ["bearer_unbound", "dpop_rejected"]);

console.log(
  failures === 0
    ? "\nセッション 13 練習問題のすべての検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
