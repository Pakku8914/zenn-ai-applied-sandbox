// api-service のクライアントロールを一時的に作り、トークンに載ることを確かめる実験スクリプト。
// verify では走らせません（realm を書き換えるため）。変更は finally で必ず元に戻します。
// 実行: docker compose exec app npx tsx src/session11/admin-client-role-experiment.ts
import { KEYCLOAK_BASE_INTERNAL, REALM } from "../session07/bookstore-tokens.js";

export type RoleRepresentation = { id: string; name: string };

/** 管理者トークンを取る。expires_in は 60 秒しかないので、長い手順では取り直す */
async function fetchAdminToken(): Promise<string> {
  const res = await fetch(`${KEYCLOAK_BASE_INTERNAL}/realms/master/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    // サンドボックス専用の固定パスワード。本番では環境変数や Secret Manager から読む
    body: new URLSearchParams({
      grant_type: "password",
      client_id: "admin-cli",
      username: "admin",
      password: "admin",
    }),
  });
  if (!res.ok) throw new Error(`管理者トークンの取得に失敗しました: ${res.status}`);
  return ((await res.json()) as { access_token: string }).access_token;
}

/** 利用者を username で引く */
async function findUser(token: string, username: string): Promise<{ id: string; username: string }> {
  const res = await fetch(
    `${KEYCLOAK_BASE_INTERNAL}/admin/realms/${REALM}/users?username=${encodeURIComponent(username)}`,
    { headers: { authorization: `Bearer ${token}` } },
  );
  const users = (await res.json()) as ReadonlyArray<{ id: string; username: string }>;
  const user = users[0];
  if (user === undefined) throw new Error(`${username} が見つかりません`);
  return user;
}
import { decodeJwtPart, loginHeadless } from "../test-helpers/headless-login.js";
import { extractFacts, factsLine } from "./api-authz-claims.js";

const ROLE_NAME = "orders-admin";
const RESOURCE_CLIENT = "api-service";

type ClientRepresentation = { id: string; clientId: string };

async function adminFetch(
  token: string,
  path: string,
  init: { method?: string; body?: unknown } = {},
): Promise<Response> {
  const { method = "GET", body } = init;
  return fetch(`${KEYCLOAK_BASE_INTERNAL}/admin/realms/${path}`, {
    method,
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

/** クライアントの UUID を clientId から引きます（ロールの URL に必要） */
async function findClientUuid(token: string, clientId: string): Promise<string> {
  const res = await adminFetch(token, `${REALM}/clients?clientId=${clientId}`);
  if (!res.ok) throw new Error(`クライアントの検索に失敗しました: HTTP ${res.status}`);
  const client = ((await res.json()) as ClientRepresentation[])[0];
  if (client === undefined) throw new Error(`${clientId} が見つかりません`);
  return client.id;
}

/** bob でログインし直して、トークンに何が載っているかを表示します */
async function showBobRoles(label: string): Promise<void> {
  const { tokens } = await loginHeadless({ username: "bob", password: "bob-pass" });
  console.log(factsLine(label, extractFacts(decodeJwtPart(tokens.access_token, 1))));
}

const adminToken = await fetchAdminToken();
const clientUuid = await findClientUuid(adminToken, RESOURCE_CLIENT);
const bob = await findUser(adminToken, "bob");

await showBobRoles("変更前の bob");

let created = false;
let assigned: RoleRepresentation | undefined;
try {
  // 1. api-service のクライアントロールを作る
  const create = await adminFetch(adminToken, `${REALM}/clients/${clientUuid}/roles`, {
    method: "POST",
    body: { name: ROLE_NAME, description: "全店舗の注文を扱える（実験用）" },
  });
  if (create.status === 409) {
    console.log(`${ROLE_NAME} は既に存在します（前回の後片付けが終わっていない可能性があります）`);
  } else if (create.status !== 201) {
    throw new Error(`ロールの作成に失敗しました: HTTP ${create.status}`);
  }
  created = true;

  // 2. 作ったロールの表現（id を含む）を読み直す。割り当てには id が必要
  const read = await adminFetch(adminToken, `${REALM}/clients/${clientUuid}/roles/${ROLE_NAME}`);
  if (!read.ok) throw new Error(`ロールの取得に失敗しました: HTTP ${read.status}`);
  assigned = (await read.json()) as RoleRepresentation;

  // 3. bob に割り当てる
  const assign = await adminFetch(adminToken, `${REALM}/users/${bob.id}/role-mappings/clients/${clientUuid}`, {
    method: "POST",
    body: [assigned],
  });
  if (!assign.ok) throw new Error(`ロールの割り当てに失敗しました: HTTP ${assign.status}`);

  // 4. 新しくログインすると、トークンの resource_access に載ってくる
  await showBobRoles("ロールを付けた後の bob");
} finally {
  // 管理者トークンは 60 秒で切れるので、後片付けの前に取り直します
  const cleanupToken = await fetchAdminToken();
  if (assigned !== undefined) {
    await adminFetch(cleanupToken, `${REALM}/users/${bob.id}/role-mappings/clients/${clientUuid}`, {
      method: "DELETE",
      body: [assigned],
    });
  }
  if (created) {
    await adminFetch(cleanupToken, `${REALM}/clients/${clientUuid}/roles/${ROLE_NAME}`, { method: "DELETE" });
  }
  await showBobRoles("元に戻した後の bob");
}
