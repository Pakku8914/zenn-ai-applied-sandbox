// RS256 の鍵プロバイダを priority 200 で 1 つ足し、JWKS に鍵が 2 本並ぶこと・
// 新しいトークンの kid が変わること・古いトークンが検証を続けられることを観察する実験スクリプト。
// 足したプロバイダは finally で必ず削除します。
//
// verify では走らせません（realm の鍵プロバイダを操作するため、繰り返し実行すると不安定になります）。
// 途中で止めてしまったときは
//   docker compose down -v && docker compose up -d --wait
// で realm を作り直せます（Keycloak のデータは消えますが、bookstore realm は再 import されます）。
//
// 実行: docker compose exec app npx tsx src/session16/admin-key-rotation-experiment.ts
import type { JSONWebKeySet } from "jose";
import { rejectReason, verifyAccessToken } from "../session04/api-service-verify-jwt.js";
import { decodeJwtPart, loginHeadless } from "../test-helpers/headless-login.js";
import {
  REALM,
  adminFetch,
  fetchAdminToken,
  fetchJwks,
  fetchPublishedKeys,
  signingKeys,
  verifyWithKeySet,
} from "./bookstore-keys.js";

/** 足す鍵プロバイダの名前と優先度。priority が高いほうが署名に使われます */
const PROVIDER_NAME = "rsa-rotated";
const NEW_PRIORITY = "200";

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

/** トークンの JOSE ヘッダから kid を読みます（署名は検証しません） */
const kidOf = (token: string): string => decodeJwtPart<{ kid?: string }>(token, 0).kid ?? "(なし)";

/** いま JWKS に載っている RS256 の署名鍵の kid */
async function publishedSigningKids(): Promise<string[]> {
  return signingKeys(await fetchPublishedKeys()).map((key) => key.kid);
}

/** 鍵束を 1 つ指定して検証し、通ったか・落ちた理由を 1 行で返します */
async function probe(token: string, jwks: JSONWebKeySet): Promise<string> {
  try {
    await verifyWithKeySet(token, jwks);
    return "検証できた";
  } catch (err) {
    return `検証できない（${rejectReason(err)}）`;
  }
}

/**
 * realm の UUID を取ります。
 * component の parentId に realm 名（bookstore）を渡すと 201 が返るのに鍵が生成されません。
 * 既存の鍵プロバイダはすべて realm の UUID を parentId に持っています。
 */
async function fetchRealmUuid(token: string): Promise<string> {
  const res = await adminFetch(token, `/realms/${REALM}`);
  if (!res.ok) throw new Error(`realm の取得に失敗しました: HTTP ${res.status}`);
  const realm = (await res.json()) as { id?: string };
  if (typeof realm.id !== "string") throw new Error("realm の id が取得できませんでした");
  return realm.id;
}

const adminToken = await fetchAdminToken();
const realmUuid = await fetchRealmUuid(adminToken);
console.log(`realm の UUID: ${realmUuid}`);

// === 変更前 ===
const before = await loginHeadless();
const oldToken = before.tokens.access_token;
const jwksBefore = await fetchJwks();
console.log("\n=== 変更前 ===");
console.log(`JWKS の RS256 署名鍵: ${JSON.stringify(await publishedSigningKids())}`);
console.log(`発行されたトークンの kid: ${kidOf(oldToken)}`);
console.log(`古いトークンを変更前の鍵束で: ${await probe(oldToken, jwksBefore)}`);

let componentId = "";
/** 足した鍵で署名されたトークン。鍵を消した後に「消しすぎ」を観察するために外に出しておきます */
let newToken = "";
try {
  // 1. RS256 の鍵プロバイダを priority 200 で足す。config は priority と algorithm だけでよい
  const res = await adminFetch(adminToken, `/realms/${REALM}/components`, {
    method: "POST",
    body: {
      name: PROVIDER_NAME,
      providerId: "rsa-generated",
      providerType: "org.keycloak.keys.KeyProvider",
      parentId: realmUuid,
      config: { priority: [NEW_PRIORITY], algorithm: ["RS256"] },
    },
  });
  if (res.status !== 201) {
    throw new Error(`鍵プロバイダの追加に失敗しました: HTTP ${res.status} ${await res.text()}`);
  }
  // 作られた component の ID は Location ヘッダの末尾に入っています
  componentId = (res.headers.get("location") ?? "").split("/").pop() ?? "";
  console.log(`\n鍵プロバイダ ${PROVIDER_NAME} の追加: HTTP ${res.status}（component ${componentId}）`);

  // 2. 鍵が生成されるまで少し待つ
  await sleep(2_000);

  // === 追加後 ===
  const jwksAfter = await fetchJwks();
  const after = await loginHeadless();
  newToken = after.tokens.access_token;
  console.log("\n=== 鍵を足した後 ===");
  console.log(`JWKS の RS256 署名鍵: ${JSON.stringify(await publishedSigningKids())}`);
  console.log(`新しく発行されたトークンの kid: ${kidOf(newToken)}`);
  console.log(`古いトークンを新しい鍵束で: ${await probe(oldToken, jwksAfter)}`);
  console.log(`新しいトークンを新しい鍵束で: ${await probe(newToken, jwksAfter)}`);
  // ここが「検証側のキャッシュが古いと落ちる」の実体です
  console.log(`新しいトークンを変更前の鍵束で: ${await probe(newToken, jwksBefore)}`);

  // 3. アプリの実装コード（セッション 4 の verifyAccessToken）は 1 行も変えていません。
  //    createRemoteJWKSet は知らない kid を見ると JWKS を取り直しますが、
  //    取り直しの冷却時間の内側だと落ちることがあります（だから猶予期間が要ります）。
  try {
    await verifyAccessToken(newToken);
    console.log("アプリの検証コードをそのまま使う: 検証できた");
  } catch (err) {
    console.log(`アプリの検証コードをそのまま使う: 検証できない（${rejectReason(err)}）`);
  }
} finally {
  // 管理者トークンは 60 秒で切れるので、後片付けの前に取り直します
  const cleanupToken = await fetchAdminToken();
  if (componentId !== "") {
    const res = await adminFetch(cleanupToken, `/realms/${REALM}/components/${componentId}`, {
      method: "DELETE",
    });
    console.log(`\n鍵プロバイダ ${PROVIDER_NAME} の削除: HTTP ${res.status}`);
  }
  await sleep(1_500);
  const jwksRestored = await fetchJwks();
  console.log("\n=== 元に戻した後 ===");
  console.log(`JWKS の RS256 署名鍵: ${JSON.stringify(await publishedSigningKids())}`);
  const restored = await loginHeadless();
  console.log(`発行されたトークンの kid: ${kidOf(restored.tokens.access_token)}`);
  // 元の鍵は消していないので、元の鍵で署名されたトークンは通り続けます
  console.log(`元の鍵で署名された古いトークン: ${await probe(oldToken, jwksRestored)}`);
  // 一方、消した鍵で署名されたトークンはもう検証できません。
  // これが「猶予を待たずに鍵を消すと落ちる」の実体です（有効期限はまだ残っています）
  if (newToken !== "") {
    console.log(`消した鍵で署名されたトークン: ${await probe(newToken, jwksRestored)}`);
  }
}
