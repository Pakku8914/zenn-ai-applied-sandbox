// 受け取ったトークンを「いつまで使えるか」まで含めて持つための型と判定。
// expires_in は「受け取った時点からの残り秒数」なので、必ず絶対時刻に直して保存します。

/** トークンエンドポイントの応答のうち、寿命の管理に使う部分だけ */
export type TokenResponseLike = {
  access_token: string;
  refresh_token?: string;
  expires_in: number;
  refresh_expires_in?: number;
  scope?: string;
};

export type TokenSet = {
  accessToken: string;
  refreshToken: string;
  /** アクセストークンが切れる時刻（エポックミリ秒） */
  accessExpiresAt: number;
  /** リフレッシュトークンが切れる時刻（エポックミリ秒） */
  refreshExpiresAt: number;
  /** 実際に付与されたスコープ。要求した文字列とは違うことがあります */
  scope: string;
};

/** 期限ぎりぎりに使うと通信中に切れてしまうため、既定で 30 秒前倒しで更新します */
export const DEFAULT_SKEW_SECONDS = 30;

/**
 * トークンエンドポイントの応答を TokenSet に直します。
 * previous を渡すと、応答に含まれなかった項目を手元の値で埋めます。
 */
export function toTokenSet(
  res: TokenResponseLike,
  options: { now?: number; previous?: TokenSet } = {},
): TokenSet {
  const now = options.now ?? Date.now();
  const previous = options.previous;
  // RFC 6749 §6: 認可サーバーは新しいリフレッシュトークンを返さないこともある。
  // その場合は手元のものを使い続けます（空にすると次のリフレッシュができなくなります）。
  const refreshToken = res.refresh_token ?? previous?.refreshToken ?? "";
  const refreshExpiresAt =
    res.refresh_expires_in === undefined
      ? (previous?.refreshExpiresAt ?? now)
      : now + res.refresh_expires_in * 1000;
  return {
    accessToken: res.access_token,
    refreshToken,
    accessExpiresAt: now + res.expires_in * 1000,
    refreshExpiresAt,
    scope: res.scope ?? previous?.scope ?? "",
  };
}

/** 指定の時刻まで残り何秒あるか（過ぎていれば負の数） */
export const secondsLeft = (expiresAt: number, now: number = Date.now()): number =>
  Math.floor((expiresAt - now) / 1000);

/** アクセストークンを取り直すべきか。前倒し（skewSeconds）を必ず入れて判断します */
export function needsRefresh(
  set: TokenSet,
  now: number = Date.now(),
  skewSeconds: number = DEFAULT_SKEW_SECONDS,
): boolean {
  return set.accessExpiresAt - skewSeconds * 1000 <= now;
}

/** リフレッシュを試してよいか。ここが false なら、もう一度ログインしてもらうしかありません */
export function canRefresh(set: TokenSet, now: number = Date.now()): boolean {
  return set.refreshToken !== "" && now < set.refreshExpiresAt;
}

/**
 * 学習のためにトークンの中身を覗くだけの関数（署名は検証しません）。
 * リフレッシュトークンは仕様上は中身のない文字列（不透明）なので、
 * アプリの実装がこの中身に依存してはいけません。
 */
export function peekClaims<T = Record<string, unknown>>(token: string): T {
  const part = token.split(".")[1];
  if (part === undefined) return {} as T;
  try {
    return JSON.parse(Buffer.from(part, "base64url").toString()) as T;
  } catch {
    return {} as T;
  }
}
