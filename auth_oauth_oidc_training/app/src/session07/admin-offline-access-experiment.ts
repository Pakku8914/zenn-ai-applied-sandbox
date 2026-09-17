// alice に offline_access ロールを一時的に付けて、オフライントークンが通常のリフレッシュ
// トークンとどう違うのかを観察する実験スクリプト。ロールは finally で必ず外します。
// verify では走らせません（利用者のロールを書き換える検証は繰り返し実行すると不安定になるため）。
// このファイルは Admin REST API の呼び出しを自分の中に持っているので、単体で動きます。
import { peekClaims } from "./rp-token-store.js";
import { loginHeadless } from "../test-helpers/headless-login.js";
import { KEYCLOAK_BASE_INTERNAL, REALM } from "./bookstore-tokens.js";

type RoleRepresentation = { id: string; name: string };

/** 管理者トークンを取る。expires_in は 60 秒しかないので、長い手順では取り直す */
async function adminToken(): Promise<string> {
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

const admin = (token: string): Record<string, string> => ({
  authorization: `Bearer ${token}`,
  "content-type": "application/json",
});

async function findAliceId(token: string): Promise<string> {
  const res = await fetch(`${KEYCLOAK_BASE_INTERNAL}/admin/realms/${REALM}/users?username=alice`, {
    headers: admin(token),
  });
  const users = (await res.json()) as ReadonlyArray<{ id: string }>;
  const id = users[0]?.id;
  if (id === undefined) throw new Error("alice が見つかりません");
  return id;
}

async function findRole(token: string, name: string): Promise<RoleRepresentation> {
  const res = await fetch(`${KEYCLOAK_BASE_INTERNAL}/admin/realms/${REALM}/roles/${name}`, {
    headers: admin(token),
  });
  if (!res.ok) throw new Error(`ロール ${name} が見つかりません: ${res.status}`);
  return (await res.json()) as RoleRepresentation;
}

/** 利用者が持つ realm ロールの名前を並べる */
async function rolesOf(token: string, userId: string): Promise<string> {
  const res = await fetch(
    `${KEYCLOAK_BASE_INTERNAL}/admin/realms/${REALM}/users/${userId}/role-mappings/realm`,
    { headers: admin(token) },
  );
  const roles = (await res.json()) as ReadonlyArray<{ name: string }>;
  return roles.map((r) => r.name).sort().join(", ");
}

/** realm ロールの付け外し。POST で付与、DELETE で解除（body は同じ形） */
async function changeRole(
  token: string,
  userId: string,
  role: RoleRepresentation,
  method: "POST" | "DELETE",
): Promise<void> {
  const res = await fetch(
    `${KEYCLOAK_BASE_INTERNAL}/admin/realms/${REALM}/users/${userId}/role-mappings/realm`,
    { method, headers: admin(token), body: JSON.stringify([role]) },
  );
  if (!res.ok) throw new Error(`ロールの${method === "POST" ? "付与" : "解除"}に失敗しました: ${res.status}`);
}

/** offline_access を要求してログインし、返ったリフレッシュトークンの性質を表示する */
async function probeOffline(label: string): Promise<void> {
  try {
    const { tokens } = await loginHeadless({ scope: "openid profile email offline_access" });
    const claims = peekClaims<{ typ?: string; scope?: string }>(tokens.refresh_token ?? "");
    console.log(
      `[${label}] 成功: typ=${String(claims.typ)} refresh_expires_in=${String(tokens.refresh_expires_in)}`,
    );
    console.log(`         scope=${String(claims.scope)}`);
  } catch (err) {
    console.log(`[${label}] 拒否: ${err instanceof Error ? err.message : String(err)}`);
  }
}

const token = await adminToken();
const aliceId = await findAliceId(token);
const offlineRole = await findRole(token, "offline_access");
console.log(`alice のいまの realm ロール: ${await rolesOf(token, aliceId)}`);

console.log("\n=== 変更前（offline_access ロールなし） ===");
await probeOffline("ロールなし");

try {
  await changeRole(token, aliceId, offlineRole, "POST");
  console.log(`\nロールを付けた後: ${await rolesOf(token, aliceId)}`);
  console.log("=== alice に offline_access ロールを付けた後 ===");
  await probeOffline("ロールあり");
} finally {
  // 管理者トークンは 60 秒で切れるので、戻すときに取り直す
  const restore = await adminToken();
  await changeRole(restore, aliceId, offlineRole, "DELETE");
  console.log(`\n元に戻した後: ${await rolesOf(restore, aliceId)}`);
  await probeOffline("元に戻した");
}
