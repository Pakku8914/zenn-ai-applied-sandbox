// 練習問題 4: 旧リフレッシュトークンが再利用できてしまうことを実測するレポート。
// realm の設定は変えません（変える実験は admin-refresh-rotation-experiment.ts）。
import { RefreshError, refreshAccessToken } from "./rp-refresh.js";
import { peekClaims } from "./rp-token-store.js";
import { loginHeadless } from "../test-helpers/headless-login.js";

/** リフレッシュを試して、成功したか・拒否されたかを 1 行にします */
async function tryRefresh(refreshToken: string): Promise<{ ok: boolean; detail: string }> {
  try {
    const res = await refreshAccessToken({ refreshToken });
    return { ok: true, detail: `HTTP 200 / expires_in=${res.expires_in}` };
  } catch (err) {
    if (!(err instanceof RefreshError)) throw err;
    return { ok: false, detail: `HTTP ${err.status} ${err.error} / ${err.errorDescription}` };
  }
}

export async function buildReuseReport(): Promise<string[]> {
  const lines = ["=== リフレッシュトークンの再利用を確かめる ==="];

  const { tokens } = await loginHeadless();
  const oldRefresh = tokens.refresh_token ?? "";
  const oldJti = peekClaims<{ jti?: string }>(oldRefresh).jti;

  const first = await refreshAccessToken({ refreshToken: oldRefresh });
  const newJti = peekClaims<{ jti?: string }>(first.refresh_token ?? "").jti;
  lines.push(`1 回目のリフレッシュ: 成功（新しい refresh_token を受け取った: ${first.refresh_token !== undefined}）`);
  lines.push(`新旧の jti は別物: ${oldJti !== newJti}`);

  // 新しいトークンを受け取った後で、あえて古いほうをもう一度使ってみる
  const second = await tryRefresh(oldRefresh);
  lines.push(`旧リフレッシュトークンの 2 回目の使用: ${second.ok ? "成功してしまう" : "拒否された"}（${second.detail}）`);
  const third = await tryRefresh(oldRefresh);
  lines.push(`同じ旧トークンの 3 回目の使用: ${third.ok ? "成功してしまう" : "拒否された"}（${third.detail}）`);

  lines.push(
    `いまの realm: ${
      second.ok ? "ローテーションしていない（revokeRefreshToken が無効）" : "ローテーションしている"
    }`,
  );
  lines.push("ローテーションを有効にする設定: revokeRefreshToken=true / refreshTokenMaxReuse=0");
  lines.push("有効にしたときの想定: 旧トークンの再利用は HTTP 400 invalid_grant で拒否される");
  lines.push("再利用検知で分かること: 盗まれたトークンが使われた可能性（セッションを切るべき兆候）");
  return lines;
}

// 直接実行したときだけ表示します（verify から import しても二重に走らせないためのガード）
if (process.argv.some((arg) => arg.includes("rp-q4-reuse-report"))) {
  for (const line of await buildReuseReport()) console.log(line);
}
