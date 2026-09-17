// セッション 10 の自己検証スクリプト。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了するため、人が出力を読んで判断する必要はありません。
// realm の設定は一切書き換えません（アクセストークンの失効は「ログアウト」で起こしています）。
import type { JWTPayload } from "jose";
import { AUDIENCE, ISSUER, fetchAccessToken } from "../session04/bookstore-endpoints.js";
import { mintTokenWithOwnKey } from "../session04/attacker-forge-tokens.js";
import { decodeJwtPart, loginHeadless } from "../test-helpers/headless-login.js";
import { audiencesOf } from "./api-service-claims.js";
import { bearerChallenge, toHeaderSafe } from "./api-service-challenge.js";
import { createApiApp } from "./api-service-app.js";
import { descriptionFor, extractBearerToken } from "./api-service-middleware.js";
import { verifyIgnoringAudience } from "./api-service-audience-lab.js";
import { compareLocalAndRemote, introspect } from "./api-service-introspect.js";

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
/** aud だけ確かめない実装を差し込んだ同じ API（実験用） */
const looseApp = createApiApp({ verify: verifyIgnoringAudience });

const callRaw = async (path: string, authorization?: string, target = app): Promise<Response> =>
  await target.request(path, authorization === undefined ? undefined : { headers: { authorization } });
const call = async (path: string, token: string, target = app): Promise<Response> =>
  await callRaw(path, `Bearer ${token}`, target);
const bodyOf = async (res: Response): Promise<Record<string, unknown>> =>
  (await res.json()) as Record<string, unknown>;

console.log("=== セッション 10 の検証 ===\n");

// 1. Authorization ヘッダの取り出し（単体）
console.log("1. Authorization ヘッダの取り出し");
check("ヘッダが無い", extractBearerToken(undefined), { ok: false, reason: "missing" });
check("空文字", extractBearerToken("   "), { ok: false, reason: "missing" });
check("別のスキーム（Basic）", extractBearerToken("Basic YWxpY2U6cGFzcw=="), { ok: false, reason: "missing" });
check("Bearer だけ", extractBearerToken("Bearer"), { ok: false, reason: "malformed" });
check("トークンに空白が混ざる", extractBearerToken("Bearer a.b c.d"), { ok: false, reason: "malformed" });
check("スキームは大文字小文字を区別しない", extractBearerToken("bearer a.b.c"), { ok: true, token: "a.b.c" });
check("スキームとトークンの間の空白は複数でもよい", extractBearerToken("Bearer   a.b.c"), {
  ok: true,
  token: "a.b.c",
});

// 2. WWW-Authenticate の組み立て（ヘッダに入れてよい文字だけを残す）
console.log("\n2. WWW-Authenticate の組み立て");
check("資格情報が無いときは error を付けない", bearerChallenge("api-service"), 'Bearer realm="api-service"');
check(
  "検証に失敗したとき",
  bearerChallenge("api-service", { error: "invalid_token", description: "The aud claim did not match" }),
  'Bearer realm="api-service", error="invalid_token", error_description="The aud claim did not match"',
);
check(
  "日本語や引用符はヘッダに出さない",
  bearerChallenge("api-service", { error: "invalid_token", description: '期限切れ"です' }),
  'Bearer realm="api-service", error="invalid_token"',
);
check("引用符は落とす", toHeaderSafe('a"b'), "a b");
check("期限切れの説明", descriptionFor({ code: "ERR_JWT_EXPIRED" }), "The access token expired");
check(
  "クレーム不一致の説明",
  descriptionFor({ code: "ERR_JWT_CLAIM_VALIDATION_FAILED", claim: "aud" }),
  "The aud claim did not match",
);
check("知らない失敗の説明", descriptionFor(new Error("boom")), "The access token is not valid");

// 3. 公開エンドポイントと 401 の 3 パターン
console.log("\n3. 公開エンドポイントと 401");
const health = await callRaw("/health");
check("/health はトークン無しで 200", health.status, 200);
check("/health の応答", (await bodyOf(health))["status"], "ok");

const noHeader = await callRaw("/api/whoami");
check("トークン無しの status", noHeader.status, 401);
check("トークン無しのチャレンジ", noHeader.headers.get("www-authenticate"), 'Bearer realm="api-service"');
check("トークン無しの本文", (await bodyOf(noHeader))["error"], "unauthenticated");
check("401 はキャッシュさせない", noHeader.headers.get("cache-control"), "no-store");

const basic = await callRaw("/api/whoami", "Basic YWxpY2U6YWxpY2UtcGFzcw==");
check("Basic を送ったときのチャレンジ", basic.headers.get("www-authenticate"), 'Bearer realm="api-service"');

const broken = await callRaw("/api/whoami", "Bearer");
check("形が壊れたヘッダの status", broken.status, 401);
check(
  "形が壊れたヘッダのチャレンジ",
  broken.headers.get("www-authenticate"),
  'Bearer realm="api-service", error="invalid_request", error_description="The Authorization header is not in the Bearer <token> form"',
);
check("形が壊れたヘッダの本文", (await bodyOf(broken))["error"], "invalid_request");

// 4. 本物のアクセストークン（alice）
console.log("\n4. 本物のアクセストークン（alice）");
const alice = await loginHeadless();
const aliceToken = alice.tokens.access_token;
const aliceSub = decodeJwtPart<{ sub?: string }>(aliceToken, 1).sub;
const whoami = await call("/api/whoami", aliceToken);
const whoamiBody = await bodyOf(whoami);
check("status", whoami.status, 200);
check("成功した応答にチャレンジは付かない", whoami.headers.get("www-authenticate"), null);
check("sub", whoamiBody["subject"], aliceSub);
check("username", whoamiBody["username"], "alice");
check("トークンを出したクライアント", whoamiBody["client"], "web-app");
check("aud は配列にそろえて返す", whoamiBody["audiences"], ["api-service"]);
check("realm ロール", whoamiBody["roles"], ["customer"]);
check("残り有効秒数は 300 秒前後", Number(whoamiBody["expiresIn"]) > 280, true);

const orders = await call("/api/orders", aliceToken);
check("/api/orders の status", orders.status, 200);
check("/api/orders の中身", (await bodyOf(orders))["orders"], ["order-1001", "order-1002", "order-9001"]);

// 5. 機械のトークン（batch-worker）。aud は満たすので通る
console.log("\n5. 機械のトークン（batch-worker）");
const batchToken = await fetchAccessToken();
const batch = await call("/api/whoami", batchToken);
const batchBody = await bodyOf(batch);
check("status", batch.status, 200);
check("aud（並べ替え）", (batchBody["audiences"] as string[]).slice().sort(), ["account", "api-service"]);
check("トークンを出したクライアント", batchBody["client"], "batch-worker");

// 6. ID トークンを api-service に持ち込む（トークン置換）
console.log("\n6. ID トークンを api-service に持ち込む");
const idToken = alice.tokens.id_token ?? "";
check("ID トークンの aud", audiencesOf(decodeJwtPart<JWTPayload>(idToken, 1)), ["web-app"]);
const idStrict = await call("/api/whoami", idToken);
check("aud を検証する実装の status", idStrict.status, 401);
check(
  "aud を検証する実装のチャレンジ",
  idStrict.headers.get("www-authenticate"),
  'Bearer realm="api-service", error="invalid_token", error_description="The aud claim did not match"',
);
const idLoose = await call("/api/whoami", idToken, looseApp);
check("aud を検証しない実装の status（通ってしまう）", idLoose.status, 200);
check("通ってしまった応答の sub は alice のもの", (await bodyOf(idLoose))["subject"], aliceSub);

// 7. JWKS に無い鍵で署名されたトークン（kid が一致しない）
console.log("\n7. JWKS に無い鍵で署名されたトークン");
const own = await mintTokenWithOwnKey({ issuer: ISSUER, audience: AUDIENCE, subject: "attacker" });
check("トークンの kid", decodeJwtPart<{ kid?: string }>(own.token, 0).kid, "lab-key-1");
const ownRes = await call("/api/whoami", own.token);
check("status", ownRes.status, 401);
check(
  "チャレンジ",
  ownRes.headers.get("www-authenticate"),
  'Bearer realm="api-service", error="invalid_token", error_description="The signing key is not published in the JWKS"',
);

// 8. 401 と 403 の使い分け
console.log("\n8. 401 と 403 の使い分け");
const bob = await loginHeadless({ username: "bob", password: "bob-pass" });
const bobToken = bob.tokens.access_token;
const bobWhoami = await bodyOf(await call("/api/whoami", bobToken));
check("bob の realm ロールに staff が含まれる", (bobWhoami["roles"] as string[]).includes("staff"), true);
const bobInventory = await call("/api/inventory", bobToken);
check("staff ロールがあると 200", bobInventory.status, 200);
check("在庫の件数", ((await bodyOf(bobInventory))["inventory"] as unknown[]).length, 2);

const aliceInventory = await call("/api/inventory", aliceToken);
check("staff ロールが無いと 403", aliceInventory.status, 403);
check("403 にはチャレンジを付けない", aliceInventory.headers.get("www-authenticate"), null);
check("403 の本文", (await bodyOf(aliceInventory))["error"], "forbidden");
check("alice でも認証は通っている（/api/whoami は 200）", (await call("/api/whoami", aliceToken)).status, 200);

// 9. イントロスペクション（RFC 7662）
console.log("\n9. イントロスペクション");
const introspected = await introspect(aliceToken);
check("active", introspected.active, true);
check("token_type", introspected.token_type, "Bearer");
check("client_id はトークンの azp と同じ", introspected.client_id, "web-app");
check("username", introspected.username, "alice");
check("sub はトークンと同じ", introspected.sub, aliceSub);
check(
  "ローカル検証では見えないキーが増えている",
  ["active", "client_id", "username", "token_type"].every((key) => key in introspected),
  true,
);

// 10. 失効したあとの食い違い（ローカル検証は気づけない）
console.log("\n10. 失効したあとの食い違い");
const loggedOut = await fetch(`${ISSUER}/protocol/openid-connect/logout`, {
  method: "POST",
  headers: { "content-type": "application/x-www-form-urlencoded" },
  body: new URLSearchParams({ client_id: "web-app", refresh_token: alice.tokens.refresh_token ?? "" }),
});
check("ログアウトの要求が受け付けられた", loggedOut.ok, true);
check("同じトークンを 2 つの方法で確かめる", await compareLocalAndRemote(aliceToken), {
  local: "ok",
  remoteActive: false,
});
check("ローカル検証だけの API はまだ 200 を返す", (await call("/api/whoami", aliceToken)).status, 200);

console.log(
  failures === 0
    ? "\nセッション 10 のすべての検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
