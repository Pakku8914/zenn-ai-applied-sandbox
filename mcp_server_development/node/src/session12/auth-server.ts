/**
 * モックの認可サーバー（Authorization Server）―― 追加依存ゼロ・学習用
 *
 * ⚠️ 本番では絶対に使わないでください。1 節の表にある責務（本人確認・同意・
 *    鍵のローテーション・失効・監査）を何ひとつ実装していません。
 *    実装しているのは「RS の側から見て必要な最小の振る舞い」だけです。
 *
 *   GET  /.well-known/oauth-authorization-server  メタデータ（RFC 8414）
 *   GET  /jwks                                    公開鍵の公開（JWKS / RFC 7517）
 *   POST /register                                動的クライアント登録（RFC 7591）
 *   GET  /authorize                               認可コードの発行（PKCE 必須 / RFC 7636）
 *   POST /token                                   トークンの発行（RFC 6749 ＋ RFC 8707）
 *   POST /debug/mint                              テスト用の鋳造（MCP_AS_DEBUG=on のときだけ）
 */
import { createHash, generateKeyPairSync, randomUUID, timingSafeEqual } from "node:crypto";
import http from "node:http";

import { type RsaJwk, signJws, toRsaJwk } from "./jwt.js";
import { SUPPORTED_SCOPES } from "./scopes.js";

export const DEFAULT_AS_PORT = 9100;
/** アクセストークンの寿命。短いほど漏えいしたときの被害時間が短い */
export const DEFAULT_TOKEN_TTL_SECONDS = 300;
/** 認可コードの寿命。1 回しか使えず、すぐ失効する */
const CODE_TTL_MS = 60_000;
const MAX_BODY_BYTES = 64 * 1024;

type RegisteredClient = {
  readonly clientId: string;
  readonly clientName: string;
  readonly redirectUris: readonly string[];
  readonly scope: string;
};

type PendingCode = {
  readonly clientId: string;
  readonly redirectUri: string;
  readonly codeChallenge: string;
  readonly scope: string;
  readonly resource: string;
  readonly subject: string;
  readonly expiresAt: number;
  used: boolean;
};

export type AuthServerOptions = {
  readonly issuer: string;
  /** テスト用の鋳造口を開けるか。既定は false */
  readonly debug?: boolean;
  readonly tokenTtlSeconds?: number;
};

export type AuthServer = {
  readonly listener: http.RequestListener;
  readonly jwk: RsaJwk;
};

export function createAuthServer(options: AuthServerOptions): AuthServer {
  // 鍵はプロセス起動時に生成する。＝再起動すると kid が変わる（6 節のキャッシュがこれに耐える）
  const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const jwk = toRsaJwk(publicKey);
  const ttl = options.tokenTtlSeconds ?? DEFAULT_TOKEN_TTL_SECONDS;
  const clients = new Map<string, RegisteredClient>();
  const codes = new Map<string, PendingCode>();

  const metadata = {
    issuer: options.issuer,
    authorization_endpoint: `${options.issuer}/authorize`,
    token_endpoint: `${options.issuer}/token`,
    registration_endpoint: `${options.issuer}/register`,
    jwks_uri: `${options.issuer}/jwks`,
    response_types_supported: ["code"],
    grant_types_supported: ["authorization_code"],
    // PKCE の S256 だけ。plain を載せないことが「PKCE 必須」の宣言になる
    code_challenge_methods_supported: ["S256"],
    token_endpoint_auth_methods_supported: ["none"],
    scopes_supported: [...SUPPORTED_SCOPES],
  };

  function issueAccessToken(params: {
    subject: string;
    audience: string;
    scope: string;
    clientId: string;
    ttlSeconds: number;
  }): { accessToken: string; expiresIn: number } {
    const now = Math.floor(Date.now() / 1000);
    const accessToken = signJws(
      { alg: "RS256", typ: "JWT", kid: jwk.kid },
      {
        iss: options.issuer,
        sub: params.subject,
        // ★ ここが今章の主役。誰のためのトークンかを刻む（RFC 8707 の resource から決める）
        aud: params.audience,
        exp: now + params.ttlSeconds,
        iat: now,
        nbf: now,
        jti: randomUUID(),
        scope: params.scope,
        client_id: params.clientId,
      },
      privateKey,
    );
    return { accessToken, expiresIn: params.ttlSeconds };
  }

  async function dispatch(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    const url = new URL(req.url ?? "/", options.issuer);
    const route = `${req.method ?? "?"} ${url.pathname}`;

    if (route === "GET /.well-known/oauth-authorization-server") {
      sendJson(res, 200, metadata);
      return;
    }
    if (route === "GET /jwks") {
      sendJson(res, 200, { keys: [jwk] });
      return;
    }
    if (route === "POST /register") {
      await handleRegister(req, res);
      return;
    }
    if (route === "GET /authorize") {
      handleAuthorize(url, res);
      return;
    }
    if (route === "POST /token") {
      await handleToken(req, res);
      return;
    }
    if (route === "POST /debug/mint" && options.debug === true) {
      await handleDebugMint(req, res);
      return;
    }
    sendJson(res, 404, { error: "not_found" });
  }

  async function handleRegister(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    const body = await readJson(req);
    if (!isRecord(body)) {
      sendJson(res, 400, { error: "invalid_client_metadata" });
      return;
    }
    const redirectUris = Array.isArray(body["redirect_uris"])
      ? body["redirect_uris"].filter((value): value is string => typeof value === "string")
      : [];
    // ★ リダイレクト URI の審査は「登録時」と「認可時」の 2 回行う
    if (redirectUris.length === 0 || !redirectUris.every(isAcceptableRedirectUri)) {
      sendJson(res, 400, {
        error: "invalid_redirect_uri",
        error_description: "https、または http のループバック（127.0.0.1 / localhost）だけを登録できます",
      });
      return;
    }
    const requested = typeof body["scope"] === "string" ? body["scope"] : SUPPORTED_SCOPES.join(" ");
    const granted = requested
      .split(" ")
      .filter((scope) => SUPPORTED_SCOPES.includes(scope))
      .join(" ");
    const clientId = `mcp-client-${randomUUID()}`;
    clients.set(clientId, {
      clientId,
      clientName: typeof body["client_name"] === "string" ? body["client_name"] : "unnamed",
      redirectUris,
      scope: granted,
    });
    log(`クライアント登録: ${clientId}（scope=${granted || "(なし)"}）`);
    sendJson(res, 201, {
      client_id: clientId,
      client_id_issued_at: Math.floor(Date.now() / 1000),
      redirect_uris: redirectUris,
      grant_types: ["authorization_code"],
      response_types: ["code"],
      // 公開クライアント（ブラウザ・デスクトップ）は秘密を持てないので none
      token_endpoint_auth_method: "none",
      scope: granted,
    });
  }

  function handleAuthorize(url: URL, res: http.ServerResponse): void {
    const clientId = url.searchParams.get("client_id") ?? "";
    const redirectUri = url.searchParams.get("redirect_uri") ?? "";
    const client = clients.get(clientId);

    // ★ client_id と redirect_uri が怪しいときは「リダイレクトしない」。
    //    攻撃者の指定した URL へリダイレクトすると、それ自体が攻撃の踏み台になる
    if (client === undefined) {
      sendJson(res, 400, { error: "invalid_client" });
      return;
    }
    if (!client.redirectUris.includes(redirectUri)) {
      // 完全一致。前方一致や「ホストが同じならよい」にしてはいけない
      sendJson(res, 400, { error: "invalid_redirect_uri" });
      return;
    }

    const state = url.searchParams.get("state") ?? "";
    const fail = (error: string): void => {
      const location = new URL(redirectUri);
      location.searchParams.set("error", error);
      if (state !== "") {
        location.searchParams.set("state", state);
      }
      res.writeHead(302, { location: location.href });
      res.end();
    };

    if (url.searchParams.get("response_type") !== "code") {
      fail("unsupported_response_type");
      return;
    }
    // ★ PKCE 必須。challenge が無い／method が S256 でないリクエストは受け付けない
    const codeChallenge = url.searchParams.get("code_challenge") ?? "";
    if (codeChallenge === "" || url.searchParams.get("code_challenge_method") !== "S256") {
      fail("invalid_request");
      return;
    }
    const resource = url.searchParams.get("resource") ?? "";
    if (resource === "") {
      // どのリソース向けのトークンかが分からないと aud を決められない
      fail("invalid_target");
      return;
    }
    const requested = url.searchParams.get("scope") ?? client.scope;
    const granted = requested
      .split(" ")
      .filter((scope) => client.scope.split(" ").includes(scope))
      .join(" ");
    if (granted === "") {
      fail("invalid_scope");
      return;
    }

    // 本物の AS はここでログイン画面と同意画面を出す。モックでは固定の利用者にする
    const code = randomUUID().replaceAll("-", "");
    codes.set(code, {
      clientId,
      redirectUri,
      codeChallenge,
      scope: granted,
      resource,
      subject: "user-1001",
      expiresAt: Date.now() + CODE_TTL_MS,
      used: false,
    });
    const location = new URL(redirectUri);
    location.searchParams.set("code", code);
    if (state !== "") {
      location.searchParams.set("state", state);
    }
    log(`認可コード発行: client=${clientId} scope=${granted} resource=${resource}`);
    res.writeHead(302, { location: location.href });
    res.end();
  }

  async function handleToken(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    const raw = await readText(req);
    const form = new URLSearchParams(raw);
    if (form.get("grant_type") !== "authorization_code") {
      sendJson(res, 400, { error: "unsupported_grant_type" });
      return;
    }
    const code = form.get("code") ?? "";
    const pending = codes.get(code);
    if (pending === undefined || pending.used || pending.expiresAt < Date.now()) {
      // 使用済み・期限切れ・存在しないをすべて同じ error にする（探索の手掛かりを与えない）
      sendJson(res, 400, { error: "invalid_grant" });
      return;
    }
    // 認可コードは 1 回限り。先に使用済みにしてから検証する（並行リクエストでの二重交換を防ぐ）
    codes.set(code, { ...pending, used: true });

    if (
      form.get("client_id") !== pending.clientId ||
      form.get("redirect_uri") !== pending.redirectUri
    ) {
      sendJson(res, 400, { error: "invalid_grant" });
      return;
    }
    // ★ PKCE の検証。verifier のハッシュが、認可時に預かった challenge と一致するか
    const verifier = form.get("code_verifier") ?? "";
    if (verifier.length < 43 || !constantTimeEquals(s256(verifier), pending.codeChallenge)) {
      log("PKCE 検証に失敗しました（code_verifier が一致しません）");
      sendJson(res, 400, { error: "invalid_grant" });
      return;
    }

    const { accessToken, expiresIn } = issueAccessToken({
      subject: pending.subject,
      audience: pending.resource,
      scope: pending.scope,
      clientId: pending.clientId,
      ttlSeconds: ttl,
    });
    log(`トークン発行: sub=${pending.subject} aud=${pending.resource} scope=${pending.scope}`);
    sendJson(res, 200, {
      access_token: accessToken,
      token_type: "Bearer",
      expires_in: expiresIn,
      scope: pending.scope,
    });
  }

  /** ⚠️ テスト専用。期限切れや別 aud のトークンを作るための口 */
  async function handleDebugMint(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    const body = await readJson(req);
    if (!isRecord(body)) {
      sendJson(res, 400, { error: "invalid_request" });
      return;
    }
    const audience = typeof body["audience"] === "string" ? body["audience"] : "";
    if (audience === "") {
      sendJson(res, 400, { error: "invalid_target" });
      return;
    }
    const { accessToken, expiresIn } = issueAccessToken({
      subject: typeof body["subject"] === "string" ? body["subject"] : "user-1001",
      audience,
      scope: typeof body["scope"] === "string" ? body["scope"] : SUPPORTED_SCOPES[0] ?? "",
      clientId: "debug-mint",
      ttlSeconds: typeof body["ttlSeconds"] === "number" ? body["ttlSeconds"] : DEFAULT_TOKEN_TTL_SECONDS,
    });
    log(`⚠️ テスト用トークンを鋳造しました（aud=${audience} ttl=${expiresIn}）`);
    sendJson(res, 200, { access_token: accessToken, token_type: "Bearer", expires_in: expiresIn });
  }

  const listener: http.RequestListener = (req, res) => {
    dispatch(req, res).catch((error: unknown) => {
      log(`未処理の例外: ${error instanceof Error ? error.message : String(error)}`);
      if (!res.headersSent) {
        sendJson(res, 500, { error: "server_error" });
      } else {
        res.end();
      }
    });
  };

  return { listener, jwk };
}

/** PKCE の S256 変換。challenge = base64url(sha256(verifier)) */
export function s256(verifier: string): string {
  return createHash("sha256").update(verifier, "ascii").digest("base64url");
}

/** RFC 8252 ―― 公開クライアントには https とループバックの http だけを許す */
export function isAcceptableRedirectUri(raw: string): boolean {
  if (raw.includes("*")) {
    return false;
  }
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return false;
  }
  if (url.hash !== "") {
    return false;
  }
  if (url.protocol === "https:") {
    return true;
  }
  return url.protocol === "http:" && (url.hostname === "127.0.0.1" || url.hostname === "localhost");
}

function constantTimeEquals(a: string, b: string): boolean {
  const left = Buffer.from(a, "utf8");
  const right = Buffer.from(b, "utf8");
  // 長さが違う場合は timingSafeEqual が例外を投げるので先に弾く
  if (left.length !== right.length) {
    return false;
  }
  return timingSafeEqual(left, right);
}

async function readText(req: http.IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  let total = 0;
  for await (const chunk of req) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk));
    total += buffer.byteLength;
    if (total > MAX_BODY_BYTES) {
      req.destroy();
      return "";
    }
    chunks.push(buffer);
  }
  return Buffer.concat(chunks).toString("utf8");
}

async function readJson(req: http.IncomingMessage): Promise<unknown> {
  const text = await readText(req);
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

function sendJson(res: http.ServerResponse, status: number, payload: unknown): void {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "content-type": "application/json",
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store",
  });
  res.end(body);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** サーバープロセスのログは stderr。HTTP では stdout でも壊れませんが、本書は 1 本に統一します */
function log(message: string): void {
  console.error(`[mock-as] ${message}`);
}
