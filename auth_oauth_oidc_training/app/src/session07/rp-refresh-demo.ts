// 本文のデモ: リフレッシュの前後で何が変わり、何が変わらないのかを 1 枚にまとめます。
import { refreshAccessToken } from "./rp-refresh.js";
import { sameScopeSet } from "./rp-scope.js";
import { needsRefresh, peekClaims, secondsLeft, toTokenSet } from "./rp-token-store.js";
import { loginHeadless } from "../test-helpers/headless-login.js";

type RefreshClaims = { jti?: string; sid?: string; typ?: string };

export async function buildRefreshDemo(): Promise<string[]> {
  // ブラウザ役の検証用ヘルパーにログインしてもらい、受け取った時刻を固定して TokenSet に直す
  const { tokens } = await loginHeadless();
  const receivedAt = Date.now();
  const first = toTokenSet(tokens, { now: receivedAt });

  const renewed = await refreshAccessToken({ refreshToken: first.refreshToken });
  const second = toTokenSet(renewed, { previous: first });
  const before = peekClaims<RefreshClaims>(first.refreshToken);
  const after = peekClaims<RefreshClaims>(second.refreshToken);

  return [
    "=== リフレッシュの前後で何が変わるか ===",
    `ログイン直後: access 残り ${secondsLeft(first.accessExpiresAt, receivedAt)} 秒 / ` +
      `refresh 残り ${secondsLeft(first.refreshExpiresAt, receivedAt)} 秒`,
    `すぐに更新が必要か: ${needsRefresh(first, receivedAt)}`,
    // 期限の 20 秒前まで進んだことにすると、前倒し 30 秒の判断が効いて true になる
    `期限の 20 秒前なら更新が必要か: ${needsRefresh(first, first.accessExpiresAt - 20_000)}`,
    `更新後の access / refresh の有効期間: ${renewed.expires_in} 秒 / ${renewed.refresh_expires_in ?? -1} 秒`,
    `リフレッシュトークンの typ: ${after.typ ?? "(なし)"}`,
    `jti は変わった: ${before.jti !== after.jti}`,
    `sid は変わらない: ${before.sid === after.sid}`,
    `アクセストークンは別物になった: ${first.accessToken !== second.accessToken}`,
    `付与されたスコープは同じ集合: ${sameScopeSet(first.scope, second.scope)}`,
  ];
}

// 直接実行したときだけ表示します（verify から import しても二重に走らせないためのガード）
if (process.argv.some((arg) => arg.includes("rp-refresh-demo"))) {
  for (const line of await buildRefreshDemo()) console.log(line);
}
