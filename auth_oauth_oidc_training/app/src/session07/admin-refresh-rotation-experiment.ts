// realm の revokeRefreshToken / refreshTokenMaxReuse を一時的に有効にして、
// 旧リフレッシュトークンの再利用が拒否されるようになることを確かめる実験スクリプト。
// 変更は finally で必ず元に戻します。verify では走らせません
// （設定を書き換える検証は、繰り返し実行すると不安定になるため）。
import { KEYCLOAK_BASE_INTERNAL, REALM } from "./bookstore-tokens.js";
import { RefreshError, refreshAccessToken } from "./rp-refresh.js";
import { loginHeadless } from "../test-helpers/headless-login.js";

type Realm = Record<string, unknown> & { realm: string };

/** master realm の管理者トークン（サンドボックス専用の固定パスワード。expires_in は 60 秒） */
async function adminToken(): Promise<string> {
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

async function getRealm(token: string): Promise<Realm> {
  const res = await fetch(`${KEYCLOAK_BASE_INTERNAL}/admin/realms/${REALM}`, {
    headers: { authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`realm の取得に失敗しました: HTTP ${res.status}`);
  return (await res.json()) as Realm;
}

async function putRealm(token: string, realm: Realm): Promise<void> {
  const res = await fetch(`${KEYCLOAK_BASE_INTERNAL}/admin/realms/${REALM}`, {
    method: "PUT",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify(realm),
  });
  if (!res.ok) throw new Error(`realm の更新に失敗しました: HTTP ${res.status}`);
}

/** ログイン → 1 回リフレッシュ → 旧リフレッシュトークンをもう一度使う、を通して結果を表示します */
async function probeReuse(label: string): Promise<void> {
  const { tokens } = await loginHeadless();
  const oldRefresh = tokens.refresh_token ?? "";
  await refreshAccessToken({ refreshToken: oldRefresh });
  try {
    await refreshAccessToken({ refreshToken: oldRefresh });
    console.log(`[${label}] 旧リフレッシュトークンの再利用: 成功してしまった（ローテーションなし）`);
  } catch (err) {
    if (!(err instanceof RefreshError)) throw err;
    console.log(`[${label}] 旧リフレッシュトークンの再利用: HTTP ${err.status} ${err.error} / ${err.errorDescription}`);
  }
}

const token = await adminToken();
const realm = await getRealm(token);
console.log(
  `いまの設定: revokeRefreshToken=${String(realm["revokeRefreshToken"])} ` +
    `refreshTokenMaxReuse=${String(realm["refreshTokenMaxReuse"])}`,
);
await probeReuse("既定");

try {
  // revokeRefreshToken: 使ったリフレッシュトークンを無効にする
  // refreshTokenMaxReuse: 無効にした後、何回まで再利用を許すか（0 なら 1 回も許さない）
  await putRealm(token, { ...realm, revokeRefreshToken: true, refreshTokenMaxReuse: 0 });
  await probeReuse("ローテーション有効");
} finally {
  // 管理者トークンは 60 秒で切れるので、戻すときに取り直します
  await putRealm(await adminToken(), realm);
  await probeReuse("元に戻した");
}
