// 認可コードをアクセストークンに交換する。ここはブラウザを通らない、
// クライアントから認可サーバーへの直接の通信です。
import { CLIENT_ID, ISSUER_INTERNAL, REDIRECT_URI, tokenEndpoint } from "./bookstore-client.js";

export type TokenResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  refresh_expires_in?: number;
  refresh_token?: string;
  id_token?: string;
  scope?: string;
  session_state?: string;
};

/** 認可サーバーが返した OAuth のエラー応答（error と error_description は仕様で決まっています） */
export class TokenExchangeError extends Error {
  readonly status: number;
  readonly error: string;
  readonly errorDescription: string;

  constructor(status: number, error: string, errorDescription: string) {
    super(`トークン交換が HTTP ${status} で失敗しました: ${error} / ${errorDescription}`);
    this.status = status;
    this.error = error;
    this.errorDescription = errorDescription;
  }
}

/** 認可コードをトークンに交換します。成功すると 1 回だけトークンが返ります */
export async function exchangeCodeForTokens(args: {
  code: string;
  codeVerifier: string;
  issuer?: string;
  clientId?: string;
  redirectUri?: string;
}): Promise<TokenResponse> {
  const res = await fetch(tokenEndpoint(args.issuer ?? ISSUER_INTERNAL), {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: args.clientId ?? CLIENT_ID,
      // 認可リクエストで指定したものと同じ値でなければ受け付けられません
      redirect_uri: args.redirectUri ?? REDIRECT_URI,
      code: args.code,
      // code_challenge の「元の値」。これを出せることが、コードの持ち主である証明になります
      code_verifier: args.codeVerifier,
    }),
  });
  const body: unknown = await res.json();
  if (!res.ok) {
    const failure = body as { error?: string; error_description?: string };
    // 失敗は例外にします。status と error を持たせておくと、呼ぶ側が分岐できます
    throw new TokenExchangeError(res.status, failure.error ?? "unknown_error", failure.error_description ?? "");
  }
  return body as TokenResponse;
}
