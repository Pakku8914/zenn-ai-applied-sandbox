// ブラウザを使わずに認可コードフロー + PKCE を完走させる検証用ヘルパー。
// 本来はブラウザが担う「ログイン画面にユーザー名とパスワードを入力する」操作を、
// Keycloak が返すログインフォームの action を直接 POST することで置き換えている。
// 演習の verify.ts から使う。アプリの実装コードとしては使わない（本番のクライアントは
// 認可サーバーのログイン画面をブラウザに表示させる）。
import { createHash, randomBytes } from "node:crypto";

const ISSUER = process.env.ISSUER_INTERNAL ?? "http://keycloak:8080/realms/bookstore";

export const base64url = (input: Buffer | string): string => Buffer.from(input).toString("base64url");

/** PKCE の code_verifier と、S256 で対応づけた code_challenge を作る */
export function createPkcePair(): { codeVerifier: string; codeChallenge: string } {
  const codeVerifier = base64url(randomBytes(32));
  const codeChallenge = createHash("sha256").update(codeVerifier).digest().toString("base64url");
  return { codeVerifier, codeChallenge };
}

export type TokenResponse = {
  access_token: string;
  id_token?: string;
  refresh_token?: string;
  token_type: string;
  expires_in: number;
  refresh_expires_in?: number;
  scope?: string;
  session_state?: string;
};

export type LoginResult = {
  tokens: TokenResponse;
  state: string;
  nonce: string;
  codeVerifier: string;
  /** コールバックに付いてきたクエリパラメータ（state・code・iss・session_state） */
  callbackParams: URLSearchParams;
};

export type LoginOptions = {
  username?: string;
  password?: string;
  clientId?: string;
  redirectUri?: string;
  scope?: string;
};

/** Set-Cookie を受け取って次のリクエストに送り返すだけの最小の Cookie 入れ */
class CookieJar {
  private readonly jar = new Map<string, string>();

  absorb(res: Response): void {
    for (const raw of res.headers.getSetCookie()) {
      const pair = raw.split(";")[0] ?? "";
      const eq = pair.indexOf("=");
      if (eq <= 0) continue;
      this.jar.set(pair.slice(0, eq).trim(), pair.slice(eq + 1).trim());
    }
  }

  header(): string {
    return [...this.jar].map(([name, value]) => `${name}=${value}`).join("; ");
  }
}

/** 認可コードをアクセストークンに交換する */
export async function exchangeCode(args: {
  code: string;
  codeVerifier: string;
  clientId?: string;
  redirectUri?: string;
}): Promise<TokenResponse> {
  const { code, codeVerifier, clientId = "web-app", redirectUri = "http://localhost:3100/callback" } = args;
  const res = await fetch(`${ISSUER}/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: clientId,
      redirect_uri: redirectUri,
      code,
      code_verifier: codeVerifier,
    }),
  });
  const body: unknown = await res.json();
  if (!res.ok) throw new Error(`トークン交換が ${res.status} で失敗しました: ${JSON.stringify(body)}`);
  return body as TokenResponse;
}

/** リフレッシュトークンでアクセストークンを取り直す */
export async function refreshTokens(refreshToken: string, clientId = "web-app"): Promise<TokenResponse> {
  const res = await fetch(`${ISSUER}/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "refresh_token", client_id: clientId, refresh_token: refreshToken }),
  });
  const body: unknown = await res.json();
  if (!res.ok) throw new Error(`リフレッシュが ${res.status} で失敗しました: ${JSON.stringify(body)}`);
  return body as TokenResponse;
}

/** ブラウザ役を務めて認可コードフローを完走し、トークン一式を返す */
export async function loginHeadless(options: LoginOptions = {}): Promise<LoginResult> {
  const {
    username = "alice",
    password = "alice-pass",
    clientId = "web-app",
    redirectUri = "http://localhost:3100/callback",
    scope = "openid profile email",
  } = options;

  const { codeVerifier, codeChallenge } = createPkcePair();
  const state = base64url(randomBytes(16));
  const nonce = base64url(randomBytes(16));
  const jar = new CookieJar();

  // 1. 認可リクエスト。ログイン画面の HTML と AUTH_SESSION_ID などの Cookie が返る
  const authUrl = `${ISSUER}/protocol/openid-connect/auth?${new URLSearchParams({
    response_type: "code",
    client_id: clientId,
    redirect_uri: redirectUri,
    scope,
    state,
    nonce,
    code_challenge: codeChallenge,
    code_challenge_method: "S256",
  })}`;
  const authRes = await fetch(authUrl, { redirect: "manual" });
  jar.absorb(authRes);
  if (authRes.status !== 200) {
    throw new Error(`認可リクエストが ${authRes.status} を返しました（ログイン画面が表示されていません）`);
  }
  const html = await authRes.text();
  const form = /<form[^>]+id="kc-form-login"[^>]+action="([^"]+)"/.exec(html);
  const action = form?.[1];
  if (!action) throw new Error("ログインフォームの action を取り出せませんでした");

  // 2. ログインフォームを POST。成功するとリダイレクト URI に認可コードが付いて返る
  const loginRes = await fetch(action.replaceAll("&amp;", "&"), {
    method: "POST",
    redirect: "manual",
    headers: { "content-type": "application/x-www-form-urlencoded", cookie: jar.header() },
    body: new URLSearchParams({ username, password, credentialId: "" }),
  });
  jar.absorb(loginRes);
  const location = loginRes.headers.get("location");
  if (!location) {
    throw new Error(`ログインがリダイレクトを返しませんでした（status ${loginRes.status}）。ユーザー名とパスワードを確認してください`);
  }

  const callbackParams = new URL(location).searchParams;
  const error = callbackParams.get("error");
  if (error) throw new Error(`認可サーバーがエラーを返しました: ${error} / ${callbackParams.get("error_description") ?? ""}`);
  if (callbackParams.get("state") !== state) throw new Error("state が一致しません（CSRF の可能性）");
  const code = callbackParams.get("code");
  if (!code) throw new Error("認可コードが返りませんでした");

  // 3. 認可コードをトークンに交換する
  const tokens = await exchangeCode({ code, codeVerifier, clientId, redirectUri });
  return { tokens, state, nonce, codeVerifier, callbackParams };
}

/** JWT のヘッダ（0）またはペイロード（1）をデコードする。署名は検証しないので検証用途には使わない */
export function decodeJwtPart<T = Record<string, unknown>>(token: string, index: 0 | 1): T {
  const part = token.split(".")[index];
  if (!part) throw new Error("JWT の形式が不正です");
  return JSON.parse(Buffer.from(part, "base64url").toString()) as T;
}
