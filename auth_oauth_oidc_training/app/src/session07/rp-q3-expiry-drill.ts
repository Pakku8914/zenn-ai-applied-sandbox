// 練習問題 3: 期限の判定を境界値で点検するドリル。
// 時刻を固定しているので、いつ実行しても同じ結果になります（ネットワークも使いません）。
import { ACCESS_TOKEN_LIFESPAN, REFRESH_IDLE_TIMEOUT } from "./bookstore-tokens.js";
import { canRefresh, needsRefresh, secondsLeft, toTokenSet } from "./rp-token-store.js";
import type { TokenSet } from "./rp-token-store.js";

/** 判定の基準になる固定の時刻（テストを毎回同じ結果にするため） */
export const T0 = Date.parse("2026-09-08T09:00:00Z");

export function sampleTokenSet(): TokenSet {
  return toTokenSet(
    {
      access_token: "access-1",
      refresh_token: "refresh-1",
      expires_in: ACCESS_TOKEN_LIFESPAN,
      refresh_expires_in: REFRESH_IDLE_TIMEOUT,
      scope: "openid email profile",
    },
    { now: T0 },
  );
}

export function runExpiryDrill(): string[] {
  const set = sampleTokenSet();
  const access = set.accessExpiresAt;
  const refresh = set.refreshExpiresAt;

  return [
    "=== 期限判定のドリル ===",
    `1. 受け取った直後: needsRefresh=${needsRefresh(set, T0)} canRefresh=${canRefresh(set, T0)} 残り ${secondsLeft(access, T0)} 秒`,
    `2. 期限の 31 秒前: needsRefresh=${needsRefresh(set, access - 31_000)}`,
    `3. 期限の 30 秒前: needsRefresh=${needsRefresh(set, access - 30_000)}`,
    `4. 期限ちょうど: needsRefresh=${needsRefresh(set, access)}`,
    `5. 期限の 1 秒後: needsRefresh=${needsRefresh(set, access + 1_000)} 残り ${secondsLeft(access, access + 1_000)} 秒`,
    `6. 前倒しを 0 秒にして期限の 1 秒前: needsRefresh=${needsRefresh(set, access - 1_000, 0)}`,
    `7. refresh の期限の 1 秒前: canRefresh=${canRefresh(set, refresh - 1_000)}`,
    `8. refresh の期限ちょうど: canRefresh=${canRefresh(set, refresh)}`,
    `9. refresh_token が空: canRefresh=${canRefresh({ ...set, refreshToken: "" }, T0)}`,
    `10. expires_in をミリ秒と取り違えた: 残り ${secondsLeft(
      toTokenSet({ access_token: "a", expires_in: 0.3 }, { now: T0 }).accessExpiresAt,
      T0,
    )} 秒`,
    `11. refresh_token が返らない応答: 手元の値を引き継ぐ=${
      toTokenSet({ access_token: "access-2", expires_in: ACCESS_TOKEN_LIFESPAN }, { now: T0, previous: set })
        .refreshToken === "refresh-1"
    }`,
  ];
}

// 直接実行したときだけ表示します（verify から import しても二重に走らせないためのガード）
if (process.argv.some((arg) => arg.includes("rp-q3-expiry-drill"))) {
  for (const line of runExpiryDrill()) console.log(line);
}
