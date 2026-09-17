// 実行: docker compose exec app npx tsx src/session05/web-app-legacy-demo.ts
// 廃止された 2 つのフローと、いまも使える Client Credentials を同じ認可サーバーに投げ、
// 返ってくる応答を見比べます。realm の設定は変更しません。
import {
  IMPLICIT_ERROR_PREFIX,
  probeClientCredentials,
  probeImplicit,
  probeRopc,
} from "./web-app-legacy-probe.js";

console.log("=== 廃止されたフローを今の認可サーバーに投げてみる ===");

const implicit = await probeImplicit();
console.log("[1] implicit（response_type=token）");
console.log(`    HTTP ステータス: ${implicit.status}`);
console.log(`    エラーはフラグメント（#）に載ったか: ${implicit.inFragment}`);
console.log(`    error: ${implicit.error}`);
console.log(
  `    error_description が仕様どおりの文言で始まるか: ${implicit.errorDescription.startsWith(IMPLICIT_ERROR_PREFIX)}`,
);

const ropc = await probeRopc();
console.log("[2] ROPC（grant_type=password）");
console.log(`    HTTP ステータス: ${ropc.status}`);
console.log(`    error: ${ropc.error}`);
console.log(`    error_description: ${ropc.errorDescription}`);

const publicClient = await probeClientCredentials("web-app");
console.log("[3] Client Credentials（web-app・公開クライアント）");
console.log(`    HTTP ステータス: ${publicClient.status}`);
console.log(`    error: ${publicClient.error}`);

// 学習用サンドボックスの固定値。本番では環境変数や Secret Manager から読みます
const confidentialClient = await probeClientCredentials("batch-worker", "batch-worker-secret");
console.log("[4] Client Credentials（batch-worker・機密クライアント）");
console.log(`    HTTP ステータス: ${confidentialClient.status}`);
console.log(`    token_type: ${confidentialClient.tokenType}`);
console.log(`    expires_in: ${confidentialClient.expiresIn}`);
console.log(`    scope: ${confidentialClient.scope}`);
console.log(`    refresh_token が返ったか: ${confidentialClient.hasRefreshToken}`);

console.log("4 つのうち、いま通るのは [4] だけです。");
