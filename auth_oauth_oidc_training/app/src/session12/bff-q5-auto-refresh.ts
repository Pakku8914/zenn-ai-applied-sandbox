// 問題 5 の解答: 上流が 401 を返したら、サーバー側のリフレッシュトークンで 1 回だけ取り直します。
// ブラウザはトークンを持っていないので、この作業はブラウザに気づかれずに終わります。
// これは BFF にしたからできることです（ブラウザにトークンを置く構成では、
// リフレッシュも XSS で読める場所で行うことになります）。
import { refreshAccessToken } from "../session07/rp-refresh.js";
import type { RpSession, StoredTokens } from "../session09/rp-session-store.js";

/** 認可サーバーの応答のうち、書き戻しに使う部分だけ */
export type RefreshedTokens = {
  readonly access_token: string;
  readonly refresh_token?: string;
  readonly id_token?: string;
  readonly expires_in: number;
};

export type RefreshFn = (refreshToken: string) => Promise<RefreshedTokens>;

/** 既定は本物の認可サーバー。検証では差し替えます */
export const defaultRefresh: RefreshFn = (refreshToken) => refreshAccessToken({ refreshToken });

export type AttemptResult = {
  readonly response: Response;
  /** リフレッシュを実行したか */
  readonly refreshed: boolean;
  /** リフレッシュに失敗してセッションを捨てたか */
  readonly sessionDropped: boolean;
};

/**
 * 呼び出しを 1 回だけ再試行します。再試行する条件は次の 3 つです。
 *   1. 上流が 401 を返した（403 は権限の問題なので、取り直しても結果は変わりません）
 *   2. リフレッシュトークンが手元にある
 *   3. まだ再試行していない（2 回目が 401 でも、そこで諦めます）
 */
export async function withRefresh(
  session: RpSession,
  call: (accessToken: string) => Promise<Response>,
  options: { refresh?: RefreshFn; now?: () => number } = {},
): Promise<AttemptResult> {
  const refresh = options.refresh ?? defaultRefresh;
  const now = options.now ?? ((): number => Date.now());
  const tokens = session.tokens;
  if (tokens === undefined) {
    throw new Error("ログインしていないセッションでは呼べません");
  }

  const first = await call(tokens.accessToken);
  if (first.status !== 401) {
    return { response: first, refreshed: false, sessionDropped: false };
  }

  const refreshToken = tokens.refreshToken;
  if (refreshToken === undefined || refreshToken === "") {
    // 取り直す手段が無いので、401 をそのまま返します
    return { response: first, refreshed: false, sessionDropped: false };
  }

  let renewed: StoredTokens;
  try {
    const res = await refresh(refreshToken);
    renewed = {
      accessToken: res.access_token,
      // 応答に refresh_token が無ければ手元のものを使い続ける（セッション 7）
      refreshToken: res.refresh_token ?? refreshToken,
      idToken: res.id_token ?? tokens.idToken,
      accessTokenExpiresAt: now() + res.expires_in * 1000,
    };
  } catch {
    // 取り直せないなら、もう一度ログインしてもらうしかありません。
    // 使えないトークンを残す理由が無いので、セッションから消します
    session.tokens = undefined;
    session.user = undefined;
    return { response: first, refreshed: false, sessionDropped: true };
  }

  session.tokens = renewed; // 新しいトークンはサーバー側にだけ書き戻す
  const second = await call(renewed.accessToken);
  return { response: second, refreshed: true, sessionDropped: false };
}
