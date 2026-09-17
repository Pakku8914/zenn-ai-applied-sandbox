/**
 * PKCE とリダイレクト URI の検査を意図的に破る実験（6 ケース）
 *
 *   docker compose exec node npx tsx src/session12/break-pkce.ts
 *
 * 認可サーバーが「何を拒否しているか」を確かめるためのスクリプトです。
 * oauth-flow.ts は変更せず、低水準の関数だけを借りています。
 */
import { randomUUID } from "node:crypto";

import {
  DEFAULT_REDIRECT_URI,
  createPkcePair,
  exchangeCodeForToken,
  fetchJsonObject,
  rawRequest,
  readString,
  registerClient,
  requestAuthorizationCode,
} from "./oauth-flow.js";
import { SCOPE_DOCS_READ } from "./scopes.js";

const AS = process.env["MCP_AS_ISSUER"] ?? "http://127.0.0.1:9100";
const RESOURCE = process.env["MCP_RESOURCE"] ?? "http://127.0.0.1:3939/mcp";

const meta = await fetchJsonObject(`${AS}/.well-known/oauth-authorization-server`);
const authorizeEndpoint = readString(meta, "authorization_endpoint");
const tokenEndpoint = readString(meta, "token_endpoint");
const clientId = await registerClient({
  registrationEndpoint: readString(meta, "registration_endpoint"),
  redirectUri: DEFAULT_REDIRECT_URI,
  scope: SCOPE_DOCS_READ,
});

/** /authorize を生で叩く。パラメータを崩す必要があるので requestAuthorizationCode は使わない */
async function authorizeRaw(params: Record<string, string>): Promise<{ status: number; location: string }> {
  const url = new URL(authorizeEndpoint);
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }
  const response = await rawRequest({ method: "GET", url: url.href });
  const location = response.headers["location"];
  return {
    status: response.status,
    location: (Array.isArray(location) ? location[0] : location) ?? response.body,
  };
}

function errorOf(location: string): string {
  try {
    return new URL(location).searchParams.get("error") ?? "(なし)";
  } catch {
    // リダイレクトされなかった場合は本文の JSON が入っている
    return location;
  }
}

// -------------------------------------------------------------- [1/6] 正常系
const ok = createPkcePair();
const okState = randomUUID();
const okCode = await requestAuthorizationCode({
  authorizationEndpoint: authorizeEndpoint,
  clientId,
  redirectUri: DEFAULT_REDIRECT_URI,
  codeChallenge: ok.challenge,
  scope: SCOPE_DOCS_READ,
  resource: RESOURCE,
  state: okState,
});
const okToken = await exchangeCodeForToken({
  tokenEndpoint,
  code: okCode,
  redirectUri: DEFAULT_REDIRECT_URI,
  clientId,
  codeVerifier: ok.verifier,
  resource: RESOURCE,
});
console.log(`[1/6] 正常系: scope=${okToken.scope} expires_in=${okToken.expiresIn}`);

// ------------------------------------------------------------ [2/6] plain 禁止
const plain = await authorizeRaw({
  response_type: "code",
  client_id: clientId,
  redirect_uri: DEFAULT_REDIRECT_URI,
  code_challenge: "plain-challenge-value",
  code_challenge_method: "plain",
  scope: SCOPE_DOCS_READ,
  resource: RESOURCE,
  state: randomUUID(),
});
console.log(`[2/6] plain: status=${plain.status} error=${errorOf(plain.location)}`);

// -------------------------------------------------- [3/6] code_challenge なし
const noChallenge = await authorizeRaw({
  response_type: "code",
  client_id: clientId,
  redirect_uri: DEFAULT_REDIRECT_URI,
  scope: SCOPE_DOCS_READ,
  resource: RESOURCE,
  state: randomUUID(),
});
console.log(`[3/6] challenge なし: status=${noChallenge.status} error=${errorOf(noChallenge.location)}`);

// ------------------------------------------- [4/6] redirect_uri が 1 文字違う
const mismatched = await authorizeRaw({
  response_type: "code",
  client_id: clientId,
  // 末尾にスラッシュを 1 つ足しただけ。これでも「別の URI」として扱われる
  redirect_uri: `${DEFAULT_REDIRECT_URI}/`,
  code_challenge: createPkcePair().challenge,
  code_challenge_method: "S256",
  scope: SCOPE_DOCS_READ,
  resource: RESOURCE,
  state: randomUUID(),
});
console.log(
  `[4/6] redirect_uri 不一致: status=${mismatched.status} body=${mismatched.location}` +
    `（リダイレクト${mismatched.status === 302 ? "あり" : "なし"}）`,
);

// ------------------------------------------------- [5/6] verifier が一致しない
const pair = createPkcePair();
const codeForWrongVerifier = await requestAuthorizationCode({
  authorizationEndpoint: authorizeEndpoint,
  clientId,
  redirectUri: DEFAULT_REDIRECT_URI,
  codeChallenge: pair.challenge,
  scope: SCOPE_DOCS_READ,
  resource: RESOURCE,
  state: randomUUID(),
});
try {
  await exchangeCodeForToken({
    tokenEndpoint,
    code: codeForWrongVerifier,
    redirectUri: DEFAULT_REDIRECT_URI,
    clientId,
    // 別のペアの verifier を使う（＝コードを横取りしただけの攻撃者の状況）
    codeVerifier: createPkcePair().verifier,
    resource: RESOURCE,
  });
  console.log("[5/6] verifier 不一致: ❌ 通ってしまいました（実装を確認してください）");
} catch (error) {
  console.log(`[5/6] verifier 不一致: 拒否されました → ${message(error)}`);
}

// --------------------------------------------------- [6/6] 認可コードの再利用
const reusePair = createPkcePair();
const reusableCode = await requestAuthorizationCode({
  authorizationEndpoint: authorizeEndpoint,
  clientId,
  redirectUri: DEFAULT_REDIRECT_URI,
  codeChallenge: reusePair.challenge,
  scope: SCOPE_DOCS_READ,
  resource: RESOURCE,
  state: randomUUID(),
});
const exchange = (): Promise<unknown> =>
  exchangeCodeForToken({
    tokenEndpoint,
    code: reusableCode,
    redirectUri: DEFAULT_REDIRECT_URI,
    clientId,
    codeVerifier: reusePair.verifier,
    resource: RESOURCE,
  });
await exchange();
try {
  await exchange();
  console.log("[6/6] code の再利用: ❌ 2 回目も通ってしまいました");
} catch (error) {
  console.log(`[6/6] code の再利用: 1 回目=成功 / 2 回目=拒否（${message(error)}）`);
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
