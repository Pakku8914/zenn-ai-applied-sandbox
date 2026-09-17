/**
 * クライアント側の OAuth 2.1 フロー（追加依存ゼロ）
 *
 * 2 節の 15 手のうち、クライアントがやる①〜⑫を関数に分けています。
 * fetch ではなく node:http を使うのは、/authorize の 302 応答の Location を
 * 確実に読むためです（fetch の redirect: "manual" の扱いは実装差があります）。
 *
 * これはクライアント側のコードなので console.log を使ってかまいません
 * （禁止されるのは stdio サーバープロセスの stdout だけです）。
 */
import { createHash, randomBytes, randomUUID } from "node:crypto";
import http from "node:http";

export const PROTOCOL_VERSION = "2025-11-25";
/**
 * 実際には待ち受けません（302 の Location を自分で読むため）。
 * それでも「登録した URI と完全一致していなければ通らない」ことは確認できます。
 */
export const DEFAULT_REDIRECT_URI = "http://127.0.0.1:6274/oauth/callback";

export type RawResponse = {
  readonly status: number;
  readonly statusMessage: string;
  readonly headers: http.IncomingHttpHeaders;
  /** [名前, 値, 名前, 値, …]。大文字小文字がそのまま見える */
  readonly rawHeaders: readonly string[];
  readonly body: string;
};

export function rawRequest(options: {
  method: string;
  url: string;
  headers?: Record<string, string>;
  body?: string;
  timeoutMs?: number;
}): Promise<RawResponse> {
  return new Promise((resolve, reject) => {
    const url = new URL(options.url);
    const headers: Record<string, string> = { host: url.host, ...options.headers };
    if (options.body !== undefined) {
      headers["content-length"] = String(Buffer.byteLength(options.body));
    }
    const request = http.request(
      {
        host: url.hostname,
        port: url.port === "" ? 80 : Number(url.port),
        path: `${url.pathname}${url.search}`,
        method: options.method,
        headers,
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (chunk: Buffer) => chunks.push(chunk));
        response.on("end", () => {
          clearTimeout(timer);
          resolve({
            status: response.statusCode ?? 0,
            statusMessage: response.statusMessage ?? "",
            headers: response.headers,
            rawHeaders: response.rawHeaders,
            body: Buffer.concat(chunks).toString("utf8"),
          });
        });
      },
    );
    // SSE で開いたままになる応答で永久に待たないための保険
    const timer = setTimeout(() => {
      request.destroy(new Error(`応答が ${options.timeoutMs ?? 10_000}ms で終わりませんでした`));
    }, options.timeoutMs ?? 10_000);
    request.on("error", (error: Error) => {
      clearTimeout(timer);
      reject(error);
    });
    if (options.body !== undefined) {
      request.write(options.body);
    }
    request.end();
  });
}

export type Challenge = {
  readonly resourceMetadata: string | undefined;
  readonly error: string | undefined;
  readonly scope: string | undefined;
  readonly raw: string;
};

export function parseWwwAuthenticate(header: string | undefined): Challenge {
  if (header === undefined) {
    return { resourceMetadata: undefined, error: undefined, scope: undefined, raw: "(なし)" };
  }
  return {
    resourceMetadata: /resource_metadata="([^"]+)"/.exec(header)?.[1],
    error: /error="([^"]+)"/.exec(header)?.[1],
    scope: /scope="([^"]+)"/.exec(header)?.[1],
    raw: header,
  };
}

export function initializeBody(id = 1): string {
  return JSON.stringify({
    jsonrpc: "2.0",
    id,
    method: "initialize",
    params: {
      protocolVersion: PROTOCOL_VERSION,
      capabilities: {},
      clientInfo: { name: "session12-client", version: "1.0.0" },
    },
  });
}

/** ① トークンを付けずに叩いて 401 を受け取る。これが発見フローの起点 */
export async function discoverChallenge(mcpUrl: string): Promise<Challenge> {
  const response = await rawRequest({
    method: "POST",
    url: mcpUrl,
    headers: { accept: "application/json, text/event-stream", "content-type": "application/json" },
    body: initializeBody(),
  });
  if (response.status !== 401) {
    throw new Error(
      `401 が返りませんでした（status=${response.status}）。サーバーが保護されていない可能性があります。`,
    );
  }
  return parseWwwAuthenticate(firstValue(response.headers["www-authenticate"]));
}

export async function fetchJsonObject(url: string): Promise<Record<string, unknown>> {
  const response = await rawRequest({ method: "GET", url, headers: { accept: "application/json" } });
  if (response.status !== 200) {
    throw new Error(`${url} の取得に失敗しました（status=${response.status}）`);
  }
  const parsed: unknown = JSON.parse(response.body);
  if (!isRecord(parsed)) {
    throw new Error(`${url} の応答が JSON オブジェクトではありません`);
  }
  return parsed;
}

export function readString(source: Record<string, unknown>, key: string): string {
  const value = source[key];
  if (typeof value !== "string") {
    throw new Error(`メタデータに ${key} がありません`);
  }
  return value;
}

/** ④ 動的クライアント登録（RFC 7591）。事前の手作業登録を不要にする */
export async function registerClient(params: {
  registrationEndpoint: string;
  redirectUri: string;
  scope: string;
  clientName?: string;
}): Promise<string> {
  const response = await rawRequest({
    method: "POST",
    url: params.registrationEndpoint,
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({
      client_name: params.clientName ?? "session12-oauth-client",
      redirect_uris: [params.redirectUri],
      grant_types: ["authorization_code"],
      response_types: ["code"],
      // 公開クライアントなのでシークレットを持たない。安全性は PKCE が担保する
      token_endpoint_auth_method: "none",
      scope: params.scope,
    }),
  });
  if (response.status !== 201) {
    throw new Error(`クライアント登録に失敗しました（status=${response.status} body=${response.body}）`);
  }
  const parsed: unknown = JSON.parse(response.body);
  if (!isRecord(parsed)) {
    throw new Error("クライアント登録の応答が不正です");
  }
  return readString(parsed, "client_id");
}

export type PkcePair = { readonly verifier: string; readonly challenge: string };

/** ⑤ PKCE。verifier は手元に隠し、そのハッシュ（challenge）だけを認可要求に載せる */
export function createPkcePair(): PkcePair {
  // RFC 7636 は 43〜128 文字を要求。32 バイトの base64url でちょうど 43 文字
  const verifier = randomBytes(32).toString("base64url");
  return {
    verifier,
    challenge: createHash("sha256").update(verifier, "ascii").digest("base64url"),
  };
}

export async function requestAuthorizationCode(params: {
  authorizationEndpoint: string;
  clientId: string;
  redirectUri: string;
  codeChallenge: string;
  scope: string;
  resource: string;
  state: string;
}): Promise<string> {
  const url = new URL(params.authorizationEndpoint);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", params.clientId);
  url.searchParams.set("redirect_uri", params.redirectUri);
  url.searchParams.set("code_challenge", params.codeChallenge);
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("scope", params.scope);
  // ★ RFC 8707。「どのリソース向けのトークンか」を明示する。この値が aud になる
  url.searchParams.set("resource", params.resource);
  url.searchParams.set("state", params.state);

  const response = await rawRequest({ method: "GET", url: url.href });
  if (response.status !== 302) {
    throw new Error(`認可要求が失敗しました（status=${response.status} body=${response.body}）`);
  }
  const location = firstValue(response.headers["location"]);
  if (location === undefined) {
    throw new Error("Location ヘッダーがありません");
  }
  const redirected = new URL(location);
  const error = redirected.searchParams.get("error");
  if (error !== null) {
    throw new Error(`認可が拒否されました（error=${error}）`);
  }
  // ★ state の一致を必ず確認する（CSRF 対策。自分が出した要求への応答だと確かめる）
  if (redirected.searchParams.get("state") !== params.state) {
    throw new Error("state が一致しません。応答を破棄します");
  }
  const code = redirected.searchParams.get("code");
  if (code === null) {
    throw new Error("認可コードがありません");
  }
  return code;
}

export async function exchangeCodeForToken(params: {
  tokenEndpoint: string;
  code: string;
  redirectUri: string;
  clientId: string;
  codeVerifier: string;
  resource: string;
}): Promise<{ accessToken: string; expiresIn: number; scope: string }> {
  const form = new URLSearchParams({
    grant_type: "authorization_code",
    code: params.code,
    redirect_uri: params.redirectUri,
    client_id: params.clientId,
    // ★ verifier をここで初めて送る。横取りされた code だけでは交換できない
    code_verifier: params.codeVerifier,
    resource: params.resource,
  });
  const response = await rawRequest({
    method: "POST",
    url: params.tokenEndpoint,
    headers: { "content-type": "application/x-www-form-urlencoded", accept: "application/json" },
    body: form.toString(),
  });
  if (response.status !== 200) {
    throw new Error(`トークン取得に失敗しました（status=${response.status} body=${response.body}）`);
  }
  const parsed: unknown = JSON.parse(response.body);
  if (!isRecord(parsed)) {
    throw new Error("トークン応答が不正です");
  }
  const expiresIn = parsed["expires_in"];
  const scope = parsed["scope"];
  return {
    accessToken: readString(parsed, "access_token"),
    expiresIn: typeof expiresIn === "number" ? expiresIn : 0,
    scope: typeof scope === "string" ? scope : "",
  };
}

export type ObtainedToken = {
  readonly accessToken: string;
  readonly expiresIn: number;
  readonly scope: string;
  readonly issuer: string;
  readonly resource: string;
  readonly steps: readonly string[];
};

/** 401 の受け取りからトークン取得までを 6 段で通す */
export async function obtainAccessToken(params: {
  mcpUrl: string;
  scope: string;
  /** 既定は mcpUrl。別の値を渡すと「他サービス向けトークン」が作れる（10 節） */
  resource?: string;
  redirectUri?: string;
}): Promise<ObtainedToken> {
  const steps: string[] = [];
  const redirectUri = params.redirectUri ?? DEFAULT_REDIRECT_URI;
  const resource = params.resource ?? params.mcpUrl;

  const challenge = await discoverChallenge(params.mcpUrl);
  steps.push(`[1/6] 401 を受け取りました → ${challenge.raw}`);
  if (challenge.resourceMetadata === undefined) {
    throw new Error("WWW-Authenticate に resource_metadata がありません");
  }

  const prm = await fetchJsonObject(challenge.resourceMetadata);
  const servers = prm["authorization_servers"];
  const issuer =
    Array.isArray(servers) && typeof servers[0] === "string" ? servers[0] : undefined;
  if (issuer === undefined) {
    throw new Error("Protected Resource Metadata に authorization_servers がありません");
  }
  steps.push(`[2/6] Protected Resource Metadata: resource=${readString(prm, "resource")} / AS=${issuer}`);

  // RFC 8414。issuer にパスがある場合は well-known の後ろにそのパスを足す（今回はパス無し）
  const asMeta = await fetchJsonObject(`${issuer}/.well-known/oauth-authorization-server`);
  const methods = asMeta["code_challenge_methods_supported"];
  if (!Array.isArray(methods) || !methods.includes("S256")) {
    throw new Error("認可サーバーが PKCE（S256）に対応していません。接続を中止します");
  }
  steps.push(
    `[3/6] Authorization Server Metadata: token_endpoint=${readString(asMeta, "token_endpoint")}` +
      ` / PKCE=S256 対応`,
  );

  const clientId = await registerClient({
    registrationEndpoint: readString(asMeta, "registration_endpoint"),
    redirectUri,
    scope: params.scope,
  });
  steps.push(`[4/6] 動的クライアント登録: client_id=${clientId}`);

  const pkce = createPkcePair();
  const state = randomUUID();
  const code = await requestAuthorizationCode({
    authorizationEndpoint: readString(asMeta, "authorization_endpoint"),
    clientId,
    redirectUri,
    codeChallenge: pkce.challenge,
    scope: params.scope,
    resource,
    state,
  });
  steps.push(`[5/6] 認可コードを取得（PKCE challenge を渡し、verifier は手元に保持）`);

  const token = await exchangeCodeForToken({
    tokenEndpoint: readString(asMeta, "token_endpoint"),
    code,
    redirectUri,
    clientId,
    codeVerifier: pkce.verifier,
    resource,
  });
  steps.push(
    `[6/6] アクセストークンを取得: scope=${token.scope} expires_in=${token.expiresIn}` +
      ` aud（要求した resource）=${resource}`,
  );

  return { ...token, issuer, resource, steps };
}

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
