// セッション 5 の自己検証スクリプト。期待値と一致しなければ非 0 で終了します。
// 実行: docker compose exec app npx tsx src/session05/verify.ts
// realm の設定は一切変更しません（読み取りと「拒否されることの確認」だけです）。
import {
  ACTORS,
  artifactsSeenBy,
  handlesPassword,
  passwordHolders,
} from "./bookstore-oauth-actors.js";
import { SITUATIONS, chooseFlow, legacyChoice } from "./web-app-flow-chooser.js";
import type { FlowId, LegacyFlowId, Situation } from "./web-app-flow-chooser.js";
import {
  IMPLICIT_ERROR_PREFIX,
  probeClientCredentials,
  probeImplicit,
  probeRopc,
} from "./web-app-legacy-probe.js";
import { createApiService } from "./api-service-q5-login-check.js";
import { fetchAccessToken } from "../session04/bookstore-endpoints.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

// --- 1. 4 つの役割と 4 種類の情報のモデル ---
check(
  "役割の並び（本書はいつもこの順序）",
  ACTORS.map((a) => a.id),
  ["resource-owner", "client", "authorization-server", "resource-server"],
);
check(
  "役割に割り当てた名前",
  ACTORS.map((a) => a.name),
  ["alice", "web-app", "keycloak", "api-service"],
);
check("パスワードを扱う役割", passwordHolders(), ["resource-owner", "authorization-server"]);
check("クライアントはパスワードを扱わない", handlesPassword("client"), false);
check("リソースサーバーはパスワードを扱わない", handlesPassword("resource-server"), false);
check("リソースサーバーが手にする情報", artifactsSeenBy("resource-server"), ["access-token"]);
check("リソースオーナーが手にする情報", artifactsSeenBy("resource-owner"), []);
check("クライアントが手にする情報", artifactsSeenBy("client"), [
  "client-credentials",
  "authorization-code",
  "access-token",
  "refresh-token",
]);

// --- 2. 用途からフローを選ぶ判断表 ---
type FlowExpectation = {
  readonly flow: FlowId;
  readonly legacy: LegacyFlowId;
  readonly removed: boolean;
};

const flowExpectations: readonly FlowExpectation[] = [
  { flow: "authorization-code+pkce", legacy: "implicit", removed: true },
  { flow: "authorization-code+pkce", legacy: "authorization-code", removed: false },
  { flow: "device-code", legacy: "ropc", removed: true },
  { flow: "client-credentials", legacy: "client-credentials", removed: false },
];

check("判断表に載せた状況の数", SITUATIONS.length, flowExpectations.length);
for (const [index, situation] of SITUATIONS.entries()) {
  const expected = flowExpectations[index];
  if (expected === undefined) {
    check(`状況 ${index} の期待値`, "未定義", "定義済み");
    continue;
  }
  const past = legacyChoice(situation);
  check(`chooseFlow: ${situation.label}`, chooseFlow(situation).flow, expected.flow);
  check(
    `legacyChoice: ${situation.label}`,
    { flow: past.flow, removed: past.removed },
    { flow: expected.legacy, removed: expected.removed },
  );
}

const impossible: Situation = {
  label: "秘密を守れないクライアントが利用者不在で動く",
  userPresent: false,
  hasBrowser: false,
  canKeepSecret: false,
};
check("利用者不在＋秘密を守れないなら使えるフローは無い", chooseFlow(impossible).flow, "none");

// --- 3. 廃止されたフローが実際に拒否されること（実測） ---
const implicit = await probeImplicit();
check("implicit の HTTP ステータス", implicit.status, 302);
check("implicit のエラーがフラグメントに載る", implicit.inFragment, true);
check("implicit の error", implicit.error, "unauthorized_client");
check(
  "implicit の error_description の先頭",
  implicit.errorDescription.startsWith(IMPLICIT_ERROR_PREFIX),
  true,
);

const ropc = await probeRopc();
check("ROPC の HTTP ステータス", ropc.status, 400);
check("ROPC の error", ropc.error, "unauthorized_client");
check("ROPC の error_description", ropc.errorDescription, "Client not allowed for direct access grants");

// --- 4. 公開クライアントと機密クライアントの違い（実測） ---
const publicClient = await probeClientCredentials("web-app");
check("公開クライアントの Client Credentials", publicClient.status, 401);
check("公開クライアントに返る error", publicClient.error, "unauthorized_client");

// 学習用サンドボックスの固定値。本番では環境変数や Secret Manager から読みます
const machine = await probeClientCredentials("batch-worker", "batch-worker-secret");
check("機密クライアントの Client Credentials", machine.status, 200);
check("返ってきたキー", machine.keys, [
  "access_token",
  "expires_in",
  "not-before-policy",
  "refresh_expires_in",
  "scope",
  "token_type",
]);
check("token_type", machine.tokenType, "Bearer");
check("expires_in", machine.expiresIn, 300);
check("scope", machine.scope, "email profile");
check("refresh_token が含まれるか（利用者不在なので含まれない）", machine.hasRefreshToken, false);
check("id_token が含まれるか（認証していないので含まれない）", machine.keys.includes("id_token"), false);

// --- 5. アクセストークンを「ログインの証明」に使うと破綻すること ---
const api = createApiService();
const machineToken = await fetchAccessToken();
const bearer = { authorization: `Bearer ${machineToken}` };

const meRes = await api.request("/me", { headers: bearer });
const me = (await meRes.json()) as Record<string, unknown>;
check("Bad な /me の HTTP ステータス", meRes.status, 200);
check("Bad な /me が「ログイン済み」と答える", me["loggedIn"], true);
check("そのトークンを要求したクライアント", me["client"], "batch-worker");

const anonymousRes = await api.request("/me");
check("トークンなしの /me", anonymousRes.status, 401);

const forbiddenRes = await api.request("/orders/order-1001", { headers: bearer });
check("Good な /orders/order-1001 に機械のトークンを持ち込む", forbiddenRes.status, 403);

const notFoundRes = await api.request("/orders/order-0000", { headers: bearer });
check("存在しない注文", notFoundRes.status, 404);

console.log(
  failures === 0
    ? "\nセッション 5 のすべての検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
