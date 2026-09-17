// 横断復習③ 問題 7: BFF の中継に「上流の 401 を 1 回だけ取り直す」を組み込みます。
// 新しく書くのは翻訳だけで、relayStatus()（S12 本文）・withRefresh()（S12 練習問題 5）・
// callApi()（mid01）・RpSession（S09）はすべて既にあるものを import します。
import { callApi } from "../mid01/mid01-api-client.js";
import type { ApiFetch } from "../mid01/mid01-api-client.js";
import { relayStatus } from "../session12/bff-api-proxy.js";
import type { BffStatus } from "../session12/bff-api-proxy.js";
import { withRefresh } from "../session12/bff-q5-auto-refresh.js";
import type { RefreshFn } from "../session12/bff-q5-auto-refresh.js";
import type { RpSession } from "../session09/rp-session-store.js";

export type RelayResult = {
  readonly status: BffStatus;
  readonly headers: Record<string, string>;
  /** ブラウザに渡す本文。トークンは 1 文字も入りません */
  readonly body: Record<string, unknown>;
  /** 取り直したか（ログに残す。ブラウザには出さない） */
  readonly refreshed: boolean;
  /** もう一度ログインしてもらう必要があるか */
  readonly reauthRequired: boolean;
};

export type RelayOptions = { readonly refresh?: RefreshFn; readonly now?: () => number };

/** 中継の応答はキャッシュさせません（別の利用者に配られると事故になります） */
const NO_STORE: Record<string, string> = { "cache-control": "no-store" };

const unauthorized = (reauthRequired: boolean, refreshed: boolean): RelayResult => ({
  status: 401,
  headers: { ...NO_STORE },
  body: { error: "unauthorized", reauth: reauthRequired },
  refreshed,
  reauthRequired,
});

/** ブラウザからの 1 回の呼び出しを api-service に中継します */
export async function relayThroughBff(
  session: RpSession,
  apiFetch: ApiFetch,
  path: string,
  options: RelayOptions = {},
): Promise<RelayResult> {
  // 1. ログイン状態の判定はここだけ。withRefresh() はトークンの無いセッションを例外にするので先に受ける
  if (session.tokens === undefined) return unauthorized(true, false);

  // 2. 呼び出しと「1 回だけの取り直し」は既にある部品に任せる（403 で再試行しないのも向こうの判断）
  const attempt = await withRefresh(session, (accessToken) => callApi(apiFetch, path, accessToken), options);
  const status = relayStatus(attempt.response.status);

  // 3. 翻訳する。上流の本文をブラウザに渡すのは 200 と 403 だけ
  if (status === 401) {
    // 取り直せたのに 2 回目も 401 なら、原因は資格情報の期限ではない。再ログインは促さない
    return unauthorized(attempt.sessionDropped, attempt.refreshed);
  }
  if (status === 502) {
    // 上流の内部事情は渡さない。JSON として読むことすらしない（壊れた上流は JSON を返さない）
    return { status, headers: { ...NO_STORE }, body: { error: "upstream_error" }, refreshed: attempt.refreshed, reauthRequired: false };
  }
  const payload = (await attempt.response.json()) as Record<string, unknown>;
  return { status, headers: { ...NO_STORE }, body: payload, refreshed: attempt.refreshed, reauthRequired: false };
}
