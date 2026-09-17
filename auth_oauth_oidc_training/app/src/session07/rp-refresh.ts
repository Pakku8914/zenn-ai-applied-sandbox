// リフレッシュトークンでアクセストークンを取り直す。
// ブラウザも利用者の操作も通らない、クライアントから認可サーバーへの直接の通信です。
import { CLIENT_ID, ISSUER_INTERNAL, tokenEndpoint } from "./bookstore-tokens.js";
import { DEFAULT_SKEW_SECONDS, canRefresh, needsRefresh, toTokenSet } from "./rp-token-store.js";
import type { TokenResponseLike, TokenSet } from "./rp-token-store.js";

export type RefreshResponse = TokenResponseLike & {
  token_type: string;
  id_token?: string;
  session_state?: string;
};

/** 認可サーバーが返した OAuth のエラー応答（error と error_description は仕様で決まっています） */
export class RefreshError extends Error {
  readonly status: number;
  readonly error: string;
  readonly errorDescription: string;

  constructor(status: number, error: string, errorDescription: string) {
    super(`リフレッシュが HTTP ${status} で失敗しました: ${error} / ${errorDescription}`);
    this.status = status;
    this.error = error;
    this.errorDescription = errorDescription;
  }
}

/**
 * grant_type=refresh_token でアクセストークンを取り直します。
 * web-app は公開クライアントなので client_secret は送りません（持っていません）。
 */
export async function refreshAccessToken(args: {
  refreshToken: string;
  clientId?: string;
  issuer?: string;
}): Promise<RefreshResponse> {
  const res = await fetch(tokenEndpoint(args.issuer ?? ISSUER_INTERNAL), {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      client_id: args.clientId ?? CLIENT_ID,
      refresh_token: args.refreshToken,
    }),
  });
  const body: unknown = await res.json();
  if (!res.ok) {
    const failure = body as { error?: string; error_description?: string };
    // 失敗は例外にします。status と error を持たせておくと、呼ぶ側が分岐できます
    throw new RefreshError(res.status, failure.error ?? "unknown_error", failure.error_description ?? "");
  }
  return body as RefreshResponse;
}

/**
 * 期限が近ければ更新し、まだ使えるならそのまま返します。
 * API を呼ぶ直前に通すのがこの関数の使い道です。
 */
export async function ensureFreshAccessToken(
  set: TokenSet,
  options: { now?: number; skewSeconds?: number } = {},
): Promise<{ set: TokenSet; refreshed: boolean }> {
  const now = options.now ?? Date.now();
  const skewSeconds = options.skewSeconds ?? DEFAULT_SKEW_SECONDS;
  if (!needsRefresh(set, now, skewSeconds)) return { set, refreshed: false };
  if (!canRefresh(set, now)) {
    throw new Error("リフレッシュトークンも使えません。もう一度ログインしてもらってください");
  }
  const res = await refreshAccessToken({ refreshToken: set.refreshToken });
  // 応答に refresh_token が無い認可サーバーもあるので、previous を渡して引き継ぎます
  return { set: toTokenSet(res, { previous: set }), refreshed: true };
}
