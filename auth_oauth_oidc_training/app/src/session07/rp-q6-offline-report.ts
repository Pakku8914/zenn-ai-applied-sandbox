// 練習問題 6: offline_access と通常のリフレッシュの違いを確かめるレポート。
// realm の設定も利用者のロールも変えません（変える実験は admin-offline-access-experiment.ts）。
import { REFRESH_IDLE_TIMEOUT } from "./bookstore-tokens.js";
import { refreshAccessToken } from "./rp-refresh.js";
import { peekClaims, toTokenSet } from "./rp-token-store.js";
import { loginHeadless } from "../test-helpers/headless-login.js";

/** 検証用ヘルパー経由のログインが失敗したときに、認可サーバーの応答を取り出します */
async function captureLoginFailure(
  run: () => Promise<unknown>,
): Promise<{ status: number; error: string; description: string }> {
  try {
    await run();
    return { status: 0, error: "成功してしまいました", description: "" };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const matched = /トークン交換が (\d+) で失敗しました: (.*)$/s.exec(message);
    if (matched === null) return { status: -1, error: message, description: "" };
    const body = JSON.parse(matched[2] ?? "{}") as { error?: string; error_description?: string };
    return {
      status: Number(matched[1] ?? "0"),
      error: body.error ?? "",
      description: body.error_description ?? "",
    };
  }
}

export async function buildOfflineReport(): Promise<string[]> {
  const lines = ["=== offline_access を確かめる ==="];

  const offline = await captureLoginFailure(() =>
    loginHeadless({ scope: "openid profile email offline_access" }),
  );
  lines.push(
    `offline_access を要求した結果: HTTP ${offline.status} ${offline.error} / ${offline.description}`,
  );

  const { tokens } = await loginHeadless();
  const set = toTokenSet(tokens);
  lines.push(`通常のリフレッシュトークンの typ: ${String(peekClaims<{ typ?: string }>(set.refreshToken).typ)}`);
  lines.push(`通常のリフレッシュトークンの有効期間: ${tokens.refresh_expires_in ?? -1} 秒`);

  const renewed = await refreshAccessToken({ refreshToken: set.refreshToken });
  lines.push(
    `リフレッシュするとアイドル期限は延びる: ${renewed.refresh_expires_in === REFRESH_IDLE_TIMEOUT}`,
  );
  lines.push(`${REFRESH_IDLE_TIMEOUT} 秒のあいだ 1 度もリフレッシュしなければ: 使えなくなる（再ログインが必要）`);
  lines.push("offline_access が必要な例: 利用者が居ない時間に動く定期処理（夜間バッチ・定期同期）");
  lines.push("offline_access を避ける例: 画面を操作している利用者のためのログイン");
  lines.push("有効化に必要なもの: 利用者に offline_access ロール（realm ロール）を割り当てる");
  lines.push("Client Credentials との違い: 利用者の許可を受けた権限かどうか");
  return lines;
}

// 直接実行したときだけ表示します（verify から import しても二重に走らせないためのガード）
if (process.argv.some((arg) => arg.includes("rp-q6-offline-report"))) {
  for (const line of await buildOfflineReport()) console.log(line);
}
