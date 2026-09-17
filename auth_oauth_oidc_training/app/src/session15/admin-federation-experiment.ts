// partner realm（外部 IdP に見立てた realm）を作り、bookstore realm から Identity Brokering で
// つないで、認可リクエストの行き先が変わることを観察する実験スクリプトです。
//
// verify では走らせません（realm を作って消す処理は、繰り返し実行すると不安定になるため）。
// 作ったものは finally ですべて消します。途中で止めてしまったときは
//   docker compose down -v && docker compose up -d --wait
// で realm を作り直せます（Keycloak のデータは消えますが、bookstore realm は再 import されます）。
//
// 実行: docker compose exec app npx tsx src/session15/admin-federation-experiment.ts
import { ISSUER_INTERNAL, ISSUER_PUBLIC, KEYCLOAK_BASE_INTERNAL, REALM } from "../session06/bookstore-client.js";
import { buildAuthorizationUrl } from "../session06/rp-authorize.js";
import { createPkcePair } from "../session06/rp-pkce.js";
import { checkTrust, missingTrust } from "./bookstore-sso-actors.js";

/** 外部 IdP に見立てる realm の名前。bookstore realm には一切触りません（IdP の登録だけ足して消します） */
const PARTNER_REALM = "partner";
/** partner realm 側に登録する、書店の Keycloak を表すクライアント */
const BROKER_CLIENT_ID = "bookstore-broker";
/** サンドボックス専用の固定値。本番では環境変数や Secret Manager から読みます */
const BROKER_CLIENT_SECRET = "bookstore-broker-secret";
/** bookstore realm 側に足す IdP の別名。ブローカーの受け口の URL に現れます */
const IDP_ALIAS = "partner";

const PARTNER_ISSUER = `${KEYCLOAK_BASE_INTERNAL}/realms/${PARTNER_REALM}`;
const BROKER_REDIRECT_URI = `${KEYCLOAK_BASE_INTERNAL}/realms/${REALM}/broker/${IDP_ALIAS}/endpoint`;

/** 管理者トークンを取ります。expires_in は 60 秒しかないので、長い手順では取り直します */
async function fetchAdminToken(): Promise<string> {
  const res = await fetch(`${KEYCLOAK_BASE_INTERNAL}/realms/master/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    // サンドボックス専用の固定パスワード。本番では環境変数や Secret Manager から読みます
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

async function adminFetch(
  token: string,
  path: string,
  init: { method?: string; body?: unknown } = {},
): Promise<Response> {
  const { method = "GET", body } = init;
  return fetch(`${KEYCLOAK_BASE_INTERNAL}/admin${path}`, {
    method,
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

/** 認可リクエストを 1 回投げて「どこへ送られるか」だけを見ます（ログインはしません） */
async function probeDestination(hint: string | null): Promise<string> {
  const { codeChallenge } = createPkcePair();
  const url = buildAuthorizationUrl({
    issuer: ISSUER_INTERNAL,
    state: "federation-experiment",
    codeChallenge,
    ...(hint === null ? {} : { override: { kc_idp_hint: hint } }),
  });
  const res = await fetch(url, { redirect: "manual" });
  const location = res.headers.get("location");
  if (location === null) {
    const body = await res.text();
    return body.includes('id="kc-form-login"')
      ? `HTTP ${res.status} → bookstore realm のログイン画面`
      : `HTTP ${res.status} → ログイン画面ではない応答`;
  }
  const target = new URL(location);
  return `HTTP ${res.status} → ${target.origin}${target.pathname}`;
}

const token = await fetchAdminToken();

console.log("=== 変更前 ===");
console.log(`kc_idp_hint なし          : ${await probeDestination(null)}`);
console.log(`kc_idp_hint=${IDP_ALIAS}       : ${await probeDestination(IDP_ALIAS)}`);

let realmCreated = false;
let idpCreated = false;
try {
  // 1. 外部 IdP 役の realm を作る
  const realmRes = await adminFetch(token, "/realms", {
    method: "POST",
    body: { realm: PARTNER_REALM, enabled: true, displayName: "提携先（外部 IdP 役）" },
  });
  if (realmRes.status === 409) {
    console.log(`\n${PARTNER_REALM} realm は既にあります（前回の後片付けが終わっていない可能性があります）`);
  } else if (realmRes.status !== 201) {
    throw new Error(`realm の作成に失敗しました: HTTP ${realmRes.status}`);
  }
  realmCreated = true;

  // 2. partner realm 側に「書店の Keycloak」を表すクライアントを登録する。
  //    redirect_uri は bookstore realm のブローカー受け口（/broker/<alias>/endpoint）です。
  const clientRes = await adminFetch(token, `/realms/${PARTNER_REALM}/clients`, {
    method: "POST",
    body: {
      clientId: BROKER_CLIENT_ID,
      name: "書店の Keycloak（ブローカー）",
      secret: BROKER_CLIENT_SECRET,
      publicClient: false,
      standardFlowEnabled: true,
      redirectUris: [BROKER_REDIRECT_URI],
    },
  });
  console.log(`\nクライアント ${BROKER_CLIENT_ID} の登録: HTTP ${clientRes.status}`);

  // 3. 提携先の社員 carol を partner realm に作る（bookstore realm の alice / bob には触りません）
  const userRes = await adminFetch(token, `/realms/${PARTNER_REALM}/users`, {
    method: "POST",
    body: {
      username: "carol",
      enabled: true,
      email: "carol@partner.example",
      emailVerified: true,
      firstName: "Carol",
      lastName: "Partner",
      credentials: [{ type: "password", value: "carol-pass", temporary: false }],
    },
  });
  console.log(`利用者 carol の作成: HTTP ${userRes.status}`);

  // 4. 信頼関係の材料が相手の discovery からそろうかを確かめる
  const partnerDiscovery = (await (
    await fetch(`${PARTNER_ISSUER}/.well-known/openid-configuration`)
  ).json()) as Record<string, unknown>;
  const trust = checkTrust(partnerDiscovery, BROKER_CLIENT_ID);
  console.log(`信頼関係で欠けている材料: ${JSON.stringify(missingTrust(trust))}`);

  // 5. bookstore realm に IdP を 1 つ足す（ここだけが bookstore realm への変更です）
  const idpRes = await adminFetch(token, `/realms/${REALM}/identity-provider/instances`, {
    method: "POST",
    body: {
      alias: IDP_ALIAS,
      providerId: "oidc",
      enabled: true,
      // 相手が「確認済み」と言ってもこちらで確認済みとは扱わない（自動リンクの事故を防ぐ）
      trustEmail: false,
      config: {
        clientId: BROKER_CLIENT_ID,
        clientSecret: BROKER_CLIENT_SECRET,
        clientAuthMethod: "client_secret_post",
        authorizationUrl: `${PARTNER_ISSUER}/protocol/openid-connect/auth`,
        tokenUrl: `${PARTNER_ISSUER}/protocol/openid-connect/token`,
        jwksUrl: `${PARTNER_ISSUER}/protocol/openid-connect/certs`,
        useJwksUrl: "true",
        defaultScope: "openid profile email",
        syncMode: "FORCE",
      },
    },
  });
  if (idpRes.status !== 201) {
    throw new Error(`IdP の登録に失敗しました: HTTP ${idpRes.status} ${await idpRes.text()}`);
  }
  idpCreated = true;
  console.log(`IdP ${IDP_ALIAS} の登録: HTTP ${idpRes.status}`);

  // 6. 属性マッピングを 1 つ足す（mapper の識別子はバージョンで変わるので、失敗しても続けます）
  const mapperRes = await adminFetch(token, `/realms/${REALM}/identity-provider/instances/${IDP_ALIAS}/mappers`, {
    method: "POST",
    body: {
      name: "partner-store-id",
      identityProviderAlias: IDP_ALIAS,
      identityProviderMapper: "hardcoded-attribute-idp-mapper",
      config: { syncMode: "INHERIT", attribute: "storeId", "attribute.value": "ueno" },
    },
  });
  console.log(`属性マッパーの追加: HTTP ${mapperRes.status}（201 以外ならこのバージョンでは識別子が違います）`);

  console.log("\n=== IdP を足した後 ===");
  console.log(`kc_idp_hint なし          : ${await probeDestination(null)}`);
  console.log(`kc_idp_hint=${IDP_ALIAS}       : ${await probeDestination(IDP_ALIAS)}`);

  // ブラウザで実際にログインしてみたい場合の入口（ホスト OS のブラウザで開きます）
  const { codeChallenge } = createPkcePair();
  console.log(
    `\nブラウザで試す URL:\n${buildAuthorizationUrl({
      issuer: ISSUER_PUBLIC,
      state: "federation-manual",
      codeChallenge,
      override: { kc_idp_hint: IDP_ALIAS },
    })}`,
  );
  console.log("（carol / carol-pass でログインすると、書店側の初回ログイン画面に進みます）");
} finally {
  // 管理者トークンは 60 秒で切れるので、後片付けの前に取り直します
  const cleanupToken = await fetchAdminToken();
  if (idpCreated) {
    const res = await adminFetch(cleanupToken, `/realms/${REALM}/identity-provider/instances/${IDP_ALIAS}`, {
      method: "DELETE",
    });
    console.log(`\nIdP ${IDP_ALIAS} の削除: HTTP ${res.status}`);
  }
  if (realmCreated) {
    const res = await adminFetch(cleanupToken, `/realms/${PARTNER_REALM}`, { method: "DELETE" });
    console.log(`${PARTNER_REALM} realm の削除: HTTP ${res.status}`);
  }
  console.log("\n=== 元に戻した後 ===");
  console.log(`kc_idp_hint=${IDP_ALIAS}       : ${await probeDestination(IDP_ALIAS)}`);
}
