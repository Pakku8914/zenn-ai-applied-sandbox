// 横断復習③ 問題 7 の確認スクリプト。上流・リフレッシュ・時計を差し替えるので外部に接続しません。
// 実行: docker compose exec app npx tsx src/review03/q7-check.ts
import type { ApiFetch } from "../mid01/mid01-api-client.js";
import type { RefreshFn } from "../session12/bff-q5-auto-refresh.js";
import type { RpSession } from "../session09/rp-session-store.js";
import { relayThroughBff } from "./q7-bff-relay.js";

const NOW = 1_700_000_000_000;

/** ログイン済み（トークンはサーバー側だけに置く）／ログイン前のセッション */
const session = (withTokens: boolean): RpSession => ({
  createdAt: NOW,
  lastSeenAt: NOW,
  attempt: undefined,
  user: withTokens ? { sub: "sub-alice", username: "alice", name: "Alice Customer" } : undefined,
  tokens: withTokens
    ? { accessToken: "access-token-1", refreshToken: "refresh-token-1", idToken: "id-token-1", accessTokenExpiresAt: NOW + 300_000 }
    : undefined,
});

const json = (body: unknown, status: number): Response =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

/** 決めた順に応答を返し、呼ばれた回数を数える上流のスタブ */
function stubApi(statuses: readonly number[]): { apiFetch: ApiFetch; calls: () => number } {
  let called = 0;
  const apiFetch: ApiFetch = async () => {
    const status = statuses[called] ?? 500;
    called += 1;
    if (status === 200) return json({ owner: "alice", count: 4, totalAmount: 6000 }, 200);
    if (status === 403) return json({ error: "forbidden", message: "staff ロールが必要です" }, 403);
    if (status === 401) return json({ error: "invalid_token" }, 401);
    return new Response("upstream is broken", { status: 500 }); // 壊れた上流は JSON を返さない
  };
  return { apiFetch, calls: () => called };
}

const okRefresh: RefreshFn = async () => ({ access_token: "access-token-2", refresh_token: "refresh-token-2", expires_in: 300 });
const failRefresh: RefreshFn = async () => {
  throw new Error("invalid_grant / Session not active");
};

/** [ラベル, ログイン済みか, 上流が返す状態の列, リフレッシュ, 期待 status, refreshed, reauth, 上流の呼び出し回数] */
type Case = readonly [string, boolean, readonly number[], RefreshFn, number, boolean, boolean, number];

const cases: readonly Case[] = [
  ["ログイン前", false, [], okRefresh, 401, false, true, 0],
  ["成功", true, [200], okRefresh, 200, false, false, 1],
  ["期限切れ → 取り直して成功", true, [401, 200], okRefresh, 200, true, false, 2],
  ["取り直しても通らない", true, [401, 401], okRefresh, 401, true, false, 2],
  ["リフレッシュが失敗", true, [401], failRefresh, 401, false, true, 1],
  ["権限が足りない", true, [403], okRefresh, 403, false, false, 1],
  ["上流が壊れている", true, [500], okRefresh, 502, false, false, 1],
];

let failed = 0;
for (const [label, loggedIn, statuses, refresh, status, refreshed, reauth, upstreamCalls] of cases) {
  const { apiFetch, calls } = stubApi(statuses);
  const result = await relayThroughBff(session(loggedIn), apiFetch, "/api/orders", { refresh, now: () => NOW });
  const serialized = JSON.stringify(result.body); // 本文にトークンが混ざっていないことも毎回確かめる
  const ok =
    result.status === status &&
    result.refreshed === refreshed &&
    result.reauthRequired === reauth &&
    calls() === upstreamCalls &&
    result.headers["cache-control"] === "no-store" &&
    !serialized.includes("token-") &&
    !serialized.includes("eyJ");
  if (!ok) failed += 1;
  console.log(`${ok ? "OK" : "NG"} ${label}: ${result.status}（期待 ${status}） refreshed=${result.refreshed} reauth=${result.reauthRequired} 上流の呼び出し=${calls()} 回`);
}

if (failed > 0) process.exit(1);
console.log("7 ケースすべてが期待どおりです");
