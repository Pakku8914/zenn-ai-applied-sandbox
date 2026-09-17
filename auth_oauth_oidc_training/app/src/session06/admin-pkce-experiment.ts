// realm 設定を一時的に変えて「plain を許してしまうとどうなるか」を確かめる実験スクリプト。
// 変更は finally で必ず元に戻します。verify では走らせません
// （設定を書き換える検証は、繰り返し実行すると不安定になるため）。
import { CLIENT_ID, ISSUER_INTERNAL, KEYCLOAK_BASE_INTERNAL, REALM } from "./bookstore-client.js";
import { buildAuthorizationUrl, probeAuthorizationRequest } from "./rp-authorize.js";
import { createPkcePair } from "./rp-pkce.js";

const PKCE_ATTRIBUTE = "pkce.code.challenge.method";

type ClientRepresentation = { id: string; clientId: string; attributes?: Record<string, string> };

/** master realm の管理者としてトークンを取ります（サンドボックス専用の固定パスワード） */
async function fetchAdminToken(): Promise<string> {
  const res = await fetch(`${KEYCLOAK_BASE_INTERNAL}/realms/master/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "password",
      client_id: "admin-cli",
      username: "admin",
      password: "admin",
    }),
  });
  if (!res.ok) throw new Error(`管理者トークンの取得に失敗しました: HTTP ${res.status}`);
  return ((await res.json()) as { access_token: string }).access_token;
}

async function fetchWebAppClient(token: string): Promise<ClientRepresentation> {
  const res = await fetch(
    `${KEYCLOAK_BASE_INTERNAL}/admin/realms/${REALM}/clients?clientId=${CLIENT_ID}`,
    { headers: { authorization: `Bearer ${token}` } },
  );
  if (!res.ok) throw new Error(`クライアント一覧の取得に失敗しました: HTTP ${res.status}`);
  const client = ((await res.json()) as ClientRepresentation[])[0];
  if (client === undefined) throw new Error(`${CLIENT_ID} が見つかりません`);
  return client;
}

async function setPkceMethod(
  token: string,
  client: ClientRepresentation,
  method: string,
): Promise<void> {
  const attributes = { ...(client.attributes ?? {}), [PKCE_ATTRIBUTE]: method };
  const res = await fetch(`${KEYCLOAK_BASE_INTERNAL}/admin/realms/${REALM}/clients/${client.id}`, {
    method: "PUT",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify({ ...client, attributes }),
  });
  if (!res.ok) throw new Error(`クライアント設定の更新に失敗しました: HTTP ${res.status}`);
}

const token = await fetchAdminToken();
const client = await fetchWebAppClient(token);
const original = client.attributes?.[PKCE_ATTRIBUTE] ?? "";
console.log(`いまの ${PKCE_ATTRIBUTE}: "${original}"`);

// plain では code_challenge と code_verifier が同じ値になります（ハッシュしないので）
const pair = createPkcePair();
const plainUrl = buildAuthorizationUrl({
  issuer: ISSUER_INTERNAL,
  state: "experiment",
  codeChallenge: pair.codeVerifier,
  override: { code_challenge_method: "plain" },
});

console.log("\n=== 変更前（S256 に固定されている） ===");
console.log(JSON.stringify(await probeAuthorizationRequest(plainUrl)));

try {
  await setPkceMethod(token, client, "");
  console.log("\n=== 属性を空にした後（plain が通ってしまう） ===");
  console.log(JSON.stringify(await probeAuthorizationRequest(plainUrl)));
} finally {
  await setPkceMethod(token, client, original === "" ? "S256" : original);
  console.log("\n=== 元に戻した後 ===");
  console.log(JSON.stringify(await probeAuthorizationRequest(plainUrl)));
}
