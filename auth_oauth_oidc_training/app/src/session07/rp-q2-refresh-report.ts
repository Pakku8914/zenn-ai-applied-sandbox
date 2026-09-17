// 練習問題 2: リフレッシュの前後を比べる点検レポート。
import { inspectClientCredentials } from "./batch-worker-check.js";
import { refreshAccessToken } from "./rp-refresh.js";
import { sameScopeSet } from "./rp-scope.js";
import { peekClaims, toTokenSet } from "./rp-token-store.js";
import { loginHeadless } from "../test-helpers/headless-login.js";

/** RFC 7519 や OIDC で決まっている（＝どの認可サーバーでも見かける）クレーム */
const STANDARD_CLAIMS = ["aud", "azp", "exp", "iat", "iss", "jti", "scope", "sid", "sub", "typ"];

type RefreshClaims = { jti?: string; sub?: string; sid?: string; typ?: string };

export async function buildRefreshReport(): Promise<string[]> {
  const lines = ["=== リフレッシュトークンの点検 ==="];

  const { tokens } = await loginHeadless();
  const before = toTokenSet(tokens);
  const claims = peekClaims<Record<string, unknown>>(before.refreshToken);
  const names = Object.keys(claims).sort();

  lines.push(`リフレッシュトークンの typ: ${String(claims["typ"])}`);
  lines.push(`クレームの数: ${names.length}`);
  lines.push(`クレームの一覧: ${names.join(", ")}`);
  lines.push(`Keycloak 独自のクレーム: ${names.filter((n) => !STANDARD_CLAIMS.includes(n)).join(", ")}`);
  lines.push(`アクセストークンの有効期間: ${tokens.expires_in} 秒`);
  lines.push(`リフレッシュトークンの有効期間: ${tokens.refresh_expires_in ?? -1} 秒`);

  const renewed = await refreshAccessToken({ refreshToken: before.refreshToken });
  const after = toTokenSet(renewed, { previous: before });
  lines.push(`更新後のアクセストークンの有効期間: ${renewed.expires_in} 秒`);
  lines.push(`更新後のリフレッシュトークンの有効期間: ${renewed.refresh_expires_in ?? -1} 秒`);

  const b = peekClaims<RefreshClaims>(before.refreshToken);
  const a = peekClaims<RefreshClaims>(after.refreshToken);
  lines.push(`jti は変わった: ${b.jti !== a.jti}`);
  lines.push(`sub は変わらない: ${b.sub === a.sub}`);
  lines.push(`sid は変わらない: ${b.sid === a.sid}`);
  lines.push(`scope は同じ集合: ${sameScopeSet(before.scope, after.scope)}`);

  // 利用者が関わらないフローには、そもそもリフレッシュトークンが無い
  const batch = await inspectClientCredentials();
  lines.push(`Client Credentials で refresh_token が返るか: ${batch.hasRefreshToken}`);
  return lines;
}

// 直接実行したときだけ表示します（verify から import しても二重に走らせないためのガード）
if (process.argv.some((arg) => arg.includes("rp-q2-refresh-report"))) {
  for (const line of await buildRefreshReport()) console.log(line);
}
